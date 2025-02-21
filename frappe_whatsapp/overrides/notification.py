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

            # fields = frappe.get_doc("DocType", self.reference_doctype).fields
            # fields += frappe.get_all(
            #     "Custom Field",
            #     filters={"dt": self.reference_doctype},
            #     fields=["fieldname"],
            # )
            # if not any(field.fieldname == self.field_name for field in fields):  # noqa
            #     frappe.throw(f"Field name {self.field_name} does not exists")

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
                self.send_template_message(doc, context)

            if self.channel == "System Notification" or self.send_system_notification:
                self.create_system_notification(doc, context)
        except:
            frappe.log_error(
                title="Failed to send notification", message=frappe.get_traceback()
            )
        super(WhatsappNotification, self).send(doc)

    def send_template_message(self, doc: Document, context):
        """Specific to Document Event triggered Server Scripts."""
        if not self.enabled:
            return

        doc_data = doc.as_dict()
        if self.condition:
            # check if condition satisfies
            if not frappe.safe_eval(
                self.condition, get_safe_globals(), dict(doc=doc_data)
            ):
                return

        template = frappe.db.get_value(
            "WhatsApp Templates", self.custom_template, fieldname="*"
        )

        recipients = self.get_receiver_list(doc, context)

        if template and recipients:
            # Pass parameter values
            components = []
            if self.custom_fields:
                parameters = []
                for field in self.custom_fields:
                    value = doc_data[field.field_name]
                    if isinstance(
                        doc_data[field.field_name],
                        (datetime.date, datetime.datetime),
                    ):
                        value = str(
                            frappe.utils.formatdate(
                                doc_data[field.field_name], "d MMM yyyy"
                            )
                        )
                        # value = str(doc_data[field.field_name])

                    if field.field_name == "owner" or field.field_name == "modified_by":
                        value = frappe.utils.get_fullname(doc_data[field.field_name])

                    parameters.append({"type": "text", "text": value})

                components = [{"type": "body", "parameters": parameters}]

            if self.custom__attach_document_print:
                # frappe.db.begin()
                key = doc.get_document_share_key()  # noqa
                frappe.db.commit()
                print_format = "Standard"
                doctype = frappe.get_doc("DocType", doc_data["doctype"])
                if doctype.custom:
                    if doctype.default_print_format:
                        print_format = doctype.default_print_format
                else:
                    default_print_format = frappe.db.get_value(
                        "Property Setter",
                        filters={
                            "doc_type": doc_data["doctype"],
                            "property": "default_print_format",
                        },
                        fieldname="value",
                    )
                    print_format = (
                        default_print_format if default_print_format else print_format
                    )
                link = get_pdf_link(
                    doc_data["doctype"], doc_data["name"], print_format=print_format
                )

                filename = f'{doc_data["name"]}.pdf'
                url = f"{frappe.utils.get_url()}{link}&key={key}"

            elif self.custom_custom_attachment:
                filename = self.file_name

                if self.custom_attach_from_field:
                    file_url = doc_data[self.custom_attach_from_field]
                    if not file_url.startswith("http"):
                        # get share key so that private files can be sent
                        key = doc.get_document_share_key()
                        file_url = f"{frappe.utils.get_url()}{file_url}&key={key}"
                else:
                    file_url = self.custom_attach

                if file_url.startswith("http"):
                    url = f"{file_url}"
                else:
                    url = f"{frappe.utils.get_url()}{file_url}"

            if template.header_type == "DOCUMENT":
                components.append(
                    {
                        "type": "header",
                        "parameters": [
                            {
                                "type": "document",
                                "document": {"link": url, "filename": filename},
                            }
                        ],
                    }
                )
            elif template.header_type == "IMAGE":
                components.append(
                    {
                        "type": "header",
                        "parameters": [{"type": "image", "image": {"link": url}}],
                    }
                )

            recipient_number = [x for x in recipients if x is not None]

            for recipient in recipient_number:
                number = recipient
                if "{" in number:
                    number = frappe.render_template(recipient, context)
                phoneNumber = self.format_number(number)

                data = {
                    "messaging_product": "whatsapp",
                    "to": self.format_number(phoneNumber),
                    "type": "template",
                    "template": {
                        "name": template.actual_name,
                        "language": {"code": template.language_code},
                        "components": components,
                    },
                }

                self.content_type = template.header_type.lower()

                self.notify(data)
        else:
            frappe.log_error(
                title="Failed to send notification", message=f"{recipients}"
            )

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
                    "message": str(data["template"]),
                    "to": data["to"],
                    "message_type": "Template",
                    "message_id": response["messages"][0]["id"],
                    "content_type": self.content_type,
                }
            ).save(ignore_permissions=True)

            frappe.msgprint("Whatsapp notification sent", indicator="green", alert=True)
            success = True

        except Exception as e:
            error_message = str(e)
            if frappe.flags.integration_request:
                response = frappe.flags.integration_request.json()["error"]
                error_message = response.get("Error", response.get("message"))

            frappe.msgprint(
                f"Failed to trigger whatsapp notification: {error_message}",
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
                    "template": self.custom_template,
                    "meta_data": meta,
                }
            ).insert(ignore_permissions=True)

    # def send_whatsapp_message(self, doc, context):
    #     recipients = self.get_receiver_list(doc, context)
    #     receiverNumbers = []
    #     data = {}
    #     for recipient in recipients:
    #         number = recipient
    #         if "{" in number:
    #             number = frappe.render_template(recipient, context)
    #         message = frappe.render_template(self.message, context)
    #         phoneNumber = self.format_number(number)

    #         data = {
    #             "messaging_product": "whatsapp",
    #             "to": self.format_number(phoneNumber),
    #             "content_type": "text",
    #             "text": {"preview_url": False, "body": message},
    #         }

    #         receiverNumbers.append(phoneNumber)

    #         self.notify(data)

    #     # frappe.msgprint(_(f"Whatsapp notification sent to {','.join(receiverNumbers)}"))

    # def notify(self, data):
    #     """Notify."""
    #     settings = frappe.get_doc(
    #         "WhatsApp Settings",
    #         "WhatsApp Settings",
    #     )
    #     token = settings.get_password("token")

    #     headers = {
    #         "authorization": f"Bearer {token}",
    #         "content-type": "application/json",
    #     }
    #     try:
    #         success = False
    #         response = make_post_request(
    #             f"{settings.url}/{settings.version}/{settings.phone_id}/messages",
    #             headers=headers,
    #             data=json.dumps(data),
    #         )

    #         if not self.get("content_type"):
    #             self.content_type = "text"

    #         frappe.get_doc(
    #             {
    #                 "doctype": "WhatsApp Message",
    #                 "type": "Outgoing",
    #                 "message": data["text"]["body"],
    #                 "to": data["to"],
    #                 "message_type": "Template",
    #                 "message_id": response["messages"][0]["id"],
    #                 "content_type": self.content_type,
    #             }
    #         ).save(ignore_permissions=True)

    #         frappe.msgprint("WhatsApp Message Triggered", indicator="green", alert=True)
    #         success = True

    #     except Exception as e:
    #         error_message = str(e)
    #         if frappe.flags.integration_request:
    #             response = frappe.flags.integration_request.json()["error"]
    #             error_message = response.get("Error", response.get("message"))

    #         frappe.msgprint(
    #             f"Failed to trigger whatsapp message: {error_message}",
    #             indicator="red",
    #             alert=True,
    #         )
    #     finally:
    #         if not success:
    #             meta = {"error": error_message}
    #         else:
    #             meta = frappe.flags.integration_request.json()
    #         frappe.get_doc(
    #             {
    #                 "doctype": "WhatsApp Notification Log",
    #                 "template": "Text Message",
    #                 "meta_data": meta,
    #             }
    #         ).insert(ignore_permissions=True)

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
