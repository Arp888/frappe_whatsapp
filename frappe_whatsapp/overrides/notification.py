import json

import frappe
from frappe import _
from frappe.desk.form.utils import get_pdf_link
from frappe.email.doctype.notification.notification import Notification, get_context
from frappe.integrations.utils import make_post_request
from frappe.model.document import Document
from frappe.utils import add_to_date, datetime, nowdate
from frappe.utils.jinja import validate_template
from frappe.utils.safe_exec import get_safe_globals, safe_exec


class WhatsappNotification(Notification):
    def validate(self):
        self.validate_whatsapp_settings()
        super(WhatsappNotification, self).validate()

    def validate_whatsapp_settings(self):
        settings = frappe.get_doc(
            "WhatsApp Settings",
            "WhatsApp Settings",
        )
        token = settings.get_password("token")

        if self.enabled and self.channel == "Whatsapp":
            if not token or not settings.url:
                frappe.throw(
                    _("Please configure whatsapp settings to send WhatsApp messages")
                )
            validate_template(self.subject)

    def send(self, doc):
        context = get_context(doc)
        context = {"doc": doc, "alert": self, "comments": None}
        if doc.get("_comments"):
            context["comments"] = json.loads(doc.get("_comments"))

        if self.is_standard:
            self.load_standard_properties(context)

        try:
            if self.channel == "Whatsapp":
                self.send_whatsapp_message(doc, context)

            if self.channel == "System Notification" or self.send_system_notification:
                self.create_system_notification(doc, context)
        except:
            frappe.log_error(
                title="Failed to send notification", message=frappe.get_traceback()
            )
        super(WhatsappNotification, self).send(doc)

    def send_whatsapp_message(self, doc, context):
        recipients = self.get_receiver_list(doc, context)
        receiverNumbers = []
        data = {}
        for recipient in recipients:
            number = recipient
            if "{" in number:
                number = frappe.render_template(recipient, context)
            message = frappe.render_template(self.message, context)
            phoneNumber = self.format_number(number)

            data = {
                "messaging_product": "whatsapp",
                "to": self.format_number(phoneNumber),
                "content_type": "text",
                "text": {"preview_url": False, "body": message},
            }

            receiverNumbers.append(phoneNumber)

            self.notify(data)

        # frappe.msgprint(_(f"Whatsapp notification sent to {','.join(receiverNumbers)}"))

    def notify(self, data):
        """Notify."""
        settings = frappe.get_doc(
            "WhatsApp Settings",
            "WhatsApp Settings",
        )
        token = settings.get_password("token")

        headers = {
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        }
        try:
            success = False
            response = make_post_request(
                f"{settings.url}/{settings.version}/{settings.phone_id}/messages",
                headers=headers,
                data=json.dumps(data),
            )

            if not self.get("content_type"):
                self.content_type = "text"

            frappe.get_doc(
                {
                    "doctype": "WhatsApp Message",
                    "type": "Outgoing",
                    "message": data["text"]["body"],
                    "to": data["to"],
                    "message_type": "Template",
                    "message_id": response["messages"][0]["id"],
                    "content_type": self.content_type,
                }
            ).save(ignore_permissions=True)

            frappe.msgprint("WhatsApp Message Triggered", indicator="green", alert=True)
            success = True

        except Exception as e:
            error_message = str(e)
            if frappe.flags.integration_request:
                response = frappe.flags.integration_request.json()["error"]
                error_message = response.get("Error", response.get("message"))

            frappe.msgprint(
                f"Failed to trigger whatsapp message: {error_message}",
                indicator="red",
                alert=True,
            )
        finally:
            if not success:
                meta = {"error": error_message}
            else:
                meta = frappe.flags.integration_request.json()
            frappe.get_doc(
                {
                    "doctype": "WhatsApp Notification Log",
                    "template": "Text Message",
                    "meta_data": meta,
                }
            ).insert(ignore_permissions=True)

    # def get_receiver_phone_number(self, number):
    #     phoneNumber = number.replace("+", "").replace("-", "")
    #     if phoneNumber.startswith("+") == True:
    #         phoneNumber = phoneNumber[1:]
    #     elif phoneNumber.startswith("00") == True:
    #         phoneNumber = phoneNumber[2:]
    #     elif phoneNumber.startswith("0") == True:
    #         if len(phoneNumber) == 10:
    #             phoneNumber = "966" + phoneNumber[1:]
    #     else:
    #         if len(phoneNumber) < 10:
    #             phoneNumber = "966" + phoneNumber
    #     if phoneNumber.startswith("0") == True:
    #         phoneNumber = phoneNumber[1:]

    #     return phoneNumber

    def format_number(self, number):
        """Format number."""
        if number.startswith("+"):
            number = number[1 : len(number)]

        return number

    def create_system_notification(self, doc, context):
        subject = self.subject
        if "{" in subject:
            subject = frappe.render_template(self.subject, context)

        attachments = self.get_attachment(doc)
        recipients, cc, bcc = self.get_list_of_recipients(doc, context)
        users = recipients + cc + bcc
        if not users:
            return

        notification_doc = {
            "type": "Alert",
            "document_type": get_reference_doctype(doc),
            "document_name": get_reference_name(doc),
            "subject": subject,
            "from_user": doc.modified_by or doc.owner,
            "email_content": frappe.render_template(self.message, context),
            "attached_file": attachments and json.dumps(attachments[0]),
        }
        enqueue_create_notification(users, notification_doc)


def get_reference_doctype(doc):
    return doc.parenttype if doc.meta.istable else doc.doctype


def get_reference_name(doc):
    return doc.parent if doc.meta.istable else doc.name


def enqueue_create_notification(users: list[str] | str, doc: dict):
    """Send notification to users.

    users: list of user emails or string of users with comma separated emails
    doc: contents of `Notification` doc
    """

    # During installation of new site, enqueue_create_notification tries to connect to Redis.
    # This breaks new site creation if Redis server is not running.
    # We do not need any notifications in fresh installation
    if frappe.flags.in_install:
        return

    doc = frappe._dict(doc)

    if isinstance(users, str):
        users = [user.strip() for user in users.split(",") if user.strip()]
    users = list(set(users))

    frappe.enqueue(
        "frappe.desk.doctype.notification_log.notification_log.make_notification_logs",
        doc=doc,
        users=users,
        now=frappe.flags.in_test,
    )
