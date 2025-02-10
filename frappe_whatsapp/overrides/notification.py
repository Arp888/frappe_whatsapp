import json

import frappe
from frappe import _
from frappe.desk.form.utils import get_pdf_link
from frappe.email.doctype.notification.notification import Notification, get_context
from frappe.integrations.utils import make_post_request
from frappe.model.document import Document
from frappe.utils import add_to_date, datetime, nowdate
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
        except:
            frappe.log_error(
                title="Failed to send notification", message=frappe.get_traceback()
            )
        super(WhatsappNotification, self).send(doc)

    # def before_insert(self):
    #     """Send message."""
    #     if self.type == "Outgoing" and self.message_type != "Template":
    #         if self.attach and not self.attach.startswith("http"):
    #             link = frappe.utils.get_url() + "/" + self.attach

    #         data = {
    #             "messaging_product": "whatsapp",
    #             "to": self.format_number(self.to),
    #             "type": self.content_type,
    #         }
    #         if self.is_reply and self.reply_to_message_id:
    #             data["context"] = {"message_id": self.reply_to_message_id}

    #         if self.content_type == "text":
    #             data["text"] = {"preview_url": True, "body": self.message}

    #         try:
    #             self.notify(data)
    #             self.status = "Success"
    #         except Exception as e:
    #             self.status = "Failed"
    #             frappe.throw(f"Failed to send message {str(e)}")
    #     elif (
    #         self.type == "Outgoing"
    #         and self.message_type == "Template"
    #         and not self.message_id
    #     ):
    #         self.send_template()

    def send_whatsapp_message(self, doc, context):
        recipients = self.get_receiver_list(doc, context)
        receiverNumbers = []
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

        frappe.msgprint(_(f"Whatsapp notification sent to {','.join(receiverNumbers)}"))

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
                    "message_type": "Manual",
                    "message_id": response["messages"][0]["id"],
                    "content_type": self.content_type,
                }
            ).save(ignore_permissions=True)
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
                    "template": self.template,
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


def on_doctype_update():
    frappe.db.add_index("WhatsApp Message", ["reference_doctype", "reference_name"])
