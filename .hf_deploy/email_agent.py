import asyncio
import email
import imaplib
import json
import logging
import os
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.policy import default
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from model_router import ModelRouter
    from learning_log import LearningLog
    _router = ModelRouter(log=LearningLog())
except ImportError:
    _router = None

logger = logging.getLogger("EmailAgent")


@dataclass
class EmailMessagePayload:
    uid: str
    message_id: str
    subject: str
    sender: str
    sender_name: str
    body: str
    preview: str
    received_at: str
    raw: Dict[str, Any] = field(default_factory=dict)


class EmailResponder:
    def __init__(
        self,
        metrics: Optional[Any] = None,
        coordinator: Optional[Any] = None,
        poll_interval: int = 20,
        processed_uid_file: Optional[str] = None,
    ):
        self.user = os.getenv("GMAIL_USER")
        self.password = os.getenv("GMAIL_PASS")
        self.imap_host = os.getenv("GMAIL_IMAP_HOST", "imap.gmail.com")
        self.imap_port = int(os.getenv("GMAIL_IMAP_PORT", "993"))
        self.smtp_host = os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("GMAIL_SMTP_PORT", "465"))
        self.poll_interval = poll_interval
        self.processed_uid_file = Path(processed_uid_file or Path.home() / ".decentralized_agent_email_uids.json")
        self.metrics = metrics
        self.coordinator = coordinator
        self.processed_uids = self._load_processed_uids()
        self.shutdown_event = asyncio.Event()
        self.router = _router

    def _load_processed_uids(self) -> List[str]:
        if self.processed_uid_file.exists():
            try:
                return json.loads(self.processed_uid_file.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_processed_uids(self) -> None:
        self.processed_uid_file.parent.mkdir(parents=True, exist_ok=True)
        self.processed_uid_file.write_text(json.dumps(self.processed_uids, indent=2), encoding="utf-8")

    def _create_imap_connection(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        client.login(self.user, self.password)
        client.select("INBOX")
        return client

    def _create_smtp_connection(self) -> smtplib.SMTP_SSL:
        context = ssl.create_default_context()
        smtp = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context)
        smtp.login(self.user, self.password)
        return smtp

    async def start(self) -> None:
        asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                unread = await asyncio.to_thread(self._fetch_unread_messages)
                if unread:
                    for payload in unread:
                        await self._process_unread_message(payload)
                else:
                    self._record_metric("email.no_unread", {})
            except Exception as exc:
                logger.exception("Email polling failed: %s", exc)
                self._record_metric("email.poll_error", {"error": str(exc)})
            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self.shutdown_event.set()

    def _fetch_unread_messages(self) -> List[EmailMessagePayload]:
        result: List[EmailMessagePayload] = []
        with self._create_imap_connection() as imap:
            status, messages = imap.search(None, "UNSEEN")
            if status != "OK":
                return result
            uids = messages[0].split()
            for uid in uids:
                uid_str = uid.decode("utf-8")
                if uid_str in self.processed_uids:
                    continue
                status, data = imap.fetch(uid, "(RFC822)")
                if status != "OK":
                    continue
                raw_email = data[0][1]
                parsed = email.message_from_bytes(raw_email, policy=default)
                body = self._extract_text(parsed)
                sender_name, sender_address = self._parse_sender(parsed.get("From", ""))
                payload = EmailMessagePayload(
                    uid=uid_str,
                    message_id=parsed.get("Message-ID", ""),
                    subject=parsed.get("Subject", ""),
                    sender=sender_address,
                    sender_name=sender_name,
                    body=body,
                    preview=body[:512],
                    received_at=parsed.get("Date", datetime.utcnow().isoformat()),
                    raw={"headers": dict(parsed.items())},
                )
                result.append(payload)
        return result

    def _extract_text(self, message: email.message.EmailMessage) -> str:
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain" and part.get_content_disposition() in (None, "inline"):
                    return part.get_content().strip()
            return "\n".join(str(part.get_content()).strip() for part in message.walk() if part.get_content_type() == "text/plain")
        return message.get_content().strip()

    def _parse_sender(self, raw_from: str) -> (str, str):
        match = re.match(r'\s*([^\"]+)\s*<(.+)>', raw_from)
        if match:
            return match.group(1).strip().strip('"'), match.group(2).strip()
        return raw_from, raw_from

    async def _process_unread_message(self, payload: EmailMessagePayload) -> None:
        self._record_metric("email.received", {"uid": payload.uid, "sender": payload.sender})
        structure = self._structure_message(payload)
        analysis = await self._analyze_message(structure)
        reply_body = self._draft_reply(payload, analysis)
        sent = await asyncio.to_thread(self._send_reply, payload, reply_body)
        if sent:
            self.processed_uids.append(payload.uid)
            self._save_processed_uids()
            self._record_metric("email.replied", {"uid": payload.uid, "recipient": payload.sender})
            if self.coordinator:
                task = self._build_email_task(payload)
                await self.coordinator.submit_task(task)
        else:
            self._record_metric("email.reply_failed", {"uid": payload.uid})

    def _structure_message(self, payload: EmailMessagePayload) -> Dict[str, Any]:
        return {
            "uid": payload.uid,
            "message_id": payload.message_id,
            "subject": payload.subject,
            "sender": payload.sender,
            "sender_name": payload.sender_name,
            "received_at": payload.received_at,
            "body_preview": payload.preview,
            "body": payload.body,
            "meta": {
                "length": len(payload.body),
                "has_links": bool(re.search(r"https?://", payload.body)),
                "is_support_request": bool(re.search(r"support|issue|help|question|urgent", payload.body, re.IGNORECASE)),
            },
        }

    async def _analyze_message(self, structured: Dict[str, Any]) -> Dict[str, Any]:
        if self.router:
            prompt = (
                f"Receive an email from {structured['sender_name']} <{structured['sender']}> with subject \"{structured['subject']}\"."
                f" Extract the action, summarize the body, and draft a concise reply." + "\n\n" + structured["body"]
            )
            response = self.router.route(prompt)
            if response.status == "success":
                return {"analysis": response.output}
        return {
            "analysis": (
                f"Email from {structured['sender_name']} about {structured['subject']}. "
                f"Body length {structured['meta']['length']}, urgent: {structured['meta']['is_support_request']}"
            )
        }

    def _draft_reply(self, payload: EmailMessagePayload, analysis: Dict[str, Any]) -> str:
        return (
            f"Hello {payload.sender_name},\n\n"
            f"Thank you for your message regarding \"{payload.subject}\". I have received your email and am processing it automatically.\n\n"
            f"Summary:\n{analysis['analysis']}\n\n"
            f"If you need immediate assistance, reply with URGENT in the subject line.\n\n"
            f"Best regards,\nAutomated Support Agent"
        )

    def _send_reply(self, payload: EmailMessagePayload, body: str) -> bool:
        try:
            message = EmailMessage()
            message["Subject"] = f"Re: {payload.subject}"
            message["From"] = self.user
            message["To"] = payload.sender
            message["In-Reply-To"] = payload.message_id
            message["References"] = payload.message_id
            message.set_content(body)
            with self._create_smtp_connection() as smtp:
                smtp.send_message(message)
            return True
        except Exception as exc:
            logger.exception("Failed to send email reply: %s", exc)
            return False

    async def process_email_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get("command") == "fetch_unread":
            unread = await asyncio.to_thread(self._fetch_unread_messages)
            return {"status": "success", "count": len(unread), "uids": [u.uid for u in unread]}
        return {"status": "failed", "message": "Unsupported email payload"}

    def _build_email_task(self, payload: EmailMessagePayload) -> Any:
        task_payload = {
            "command": f"echo 'Email from {payload.sender} with subject {payload.subject} processed'",
            "context": {
                "sender": payload.sender,
                "subject": payload.subject,
                "uid": payload.uid,
            },
        }
        from execution_core import PipelineTask, TaskType, TaskPriority
        return PipelineTask(type=TaskType.SYSTEM, priority=TaskPriority.LOW, payload=task_payload)

    def _record_metric(self, key: str, data: Dict[str, Any]) -> None:
        if self.metrics:
            self.metrics.record_email_event(key, data)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def main():
        metrics = None
        responder = EmailResponder(metrics=metrics)
        await responder.start()
        await asyncio.sleep(60)
        responder.stop()

    asyncio.run(main())
