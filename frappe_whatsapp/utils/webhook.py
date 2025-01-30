"""Webhook."""

import calendar
import json
import time

import frappe
import requests
from frappe.integrations.utils import make_post_request
from frappe.query_builder import Order
from frappe.query_builder.functions import CombineDatetime, Extract, Sum
from frappe.utils import (
    cstr,
    flt,
    get_link_to_form,
    get_time,
    getdate,
    nowdate,
    nowtime,
)
from hcapp.mine_production.api.v1.get_yearly_production_data import get_dashboard_data
from werkzeug.wrappers import Response


@frappe.whitelist(allow_guest=True)
def webhook():
    """Meta webhook."""
    if frappe.request.method == "GET":
        return get()
    return post()


def get():
    """Get."""
    hub_challenge = frappe.form_dict.get("hub.challenge")
    webhook_verify_token = frappe.db.get_single_value(
        "WhatsApp Settings", "webhook_verify_token"
    )

    if frappe.form_dict.get("hub.verify_token") != webhook_verify_token:
        frappe.throw("Verify token does not match")

    return Response(hub_challenge, status=200)


def post():
    """Post."""
    data = frappe.local.form_dict
    frappe.get_doc(
        {
            "doctype": "WhatsApp Notification Log",
            "template": "Webhook",
            "meta_data": json.dumps(data),
        }
    ).insert(ignore_permissions=True)

    messages = []
    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages", [])
    except KeyError:
        messages = data["entry"]["changes"][0]["value"].get("messages", [])

    if messages:
        for message in messages:
            message_type = message["type"]
            is_reply = True if message.get("context") else False
            reply_to_message_id = message["context"]["id"] if is_reply else None
            if message_type == "text":
                frappe.get_doc(
                    {
                        "doctype": "WhatsApp Message",
                        "type": "Incoming",
                        "from": message["from"],
                        "message": message["text"]["body"],
                        "message_id": message["id"],
                        "reply_to_message_id": reply_to_message_id,
                        "is_reply": is_reply,
                        "content_type": message_type,
                    }
                ).insert(ignore_permissions=True)
                sender = message["from"]
                text = message["text"]["body"]

                msg = ""

                if text.lower() == "hello":
                    msg = "Hi there! How can I help you?"
                elif text.lower() == "produksi":
                    prod = get_yearly_production_data()
                    if prod:
                        msg += f"*Total produksi (update {prod['last_posting_date']})*\n"
                        for key in prod.data:
                            msg += f"- {key} = {prod.data[key]["tonnage"]} {prod.data[key]["uom"]}\n"
                else:
                    msg = "Silahkan ketikkan kata kunci"

                send_response(sender, msg)

            elif message_type == "reaction":
                frappe.get_doc(
                    {
                        "doctype": "WhatsApp Message",
                        "type": "Incoming",
                        "from": message["from"],
                        "message": message["reaction"]["emoji"],
                        "reply_to_message_id": message["reaction"]["message_id"],
                        "message_id": message["id"],
                        "content_type": "reaction",
                    }
                ).insert(ignore_permissions=True)
            elif message_type == "interactive":
                frappe.get_doc(
                    {
                        "doctype": "WhatsApp Message",
                        "type": "Incoming",
                        "from": message["from"],
                        "message": message["interactive"]["nfm_reply"]["response_json"],
                        "message_id": message["id"],
                        "content_type": "flow",
                    }
                ).insert(ignore_permissions=True)
            elif message_type in ["image", "audio", "video", "document"]:
                settings = frappe.get_doc(
                    "WhatsApp Settings",
                    "WhatsApp Settings",
                )
                token = settings.get_password("token")
                url = f"{settings.url}/{settings.version}/"

                media_id = message[message_type]["id"]
                headers = {"Authorization": "Bearer " + token}
                response = requests.get(f"{url}{media_id}/", headers=headers)

                if response.status_code == 200:
                    media_data = response.json()
                    media_url = media_data.get("url")
                    mime_type = media_data.get("mime_type")
                    file_extension = mime_type.split("/")[1]

                    media_response = requests.get(media_url, headers=headers)
                    if media_response.status_code == 200:

                        file_data = media_response.content
                        file_name = (
                            f"{frappe.generate_hash(length=10)}.{file_extension}"
                        )

                        message_doc = frappe.get_doc(
                            {
                                "doctype": "WhatsApp Message",
                                "type": "Incoming",
                                "from": message["from"],
                                "message_id": message["id"],
                                "reply_to_message_id": reply_to_message_id,
                                "is_reply": is_reply,
                                "message": message[message_type].get(
                                    "caption", f"/files/{file_name}"
                                ),
                                "content_type": message_type,
                            }
                        ).insert(ignore_permissions=True)

                        file = frappe.get_doc(
                            {
                                "doctype": "File",
                                "file_name": file_name,
                                "attached_to_doctype": "WhatsApp Message",
                                "attached_to_name": message_doc.name,
                                "content": file_data,
                                "attached_to_field": "attach",
                            }
                        ).save(ignore_permissions=True)

                        message_doc.attach = file.file_url
                        message_doc.save()
            elif message_type == "button":
                frappe.get_doc(
                    {
                        "doctype": "WhatsApp Message",
                        "type": "Incoming",
                        "from": message["from"],
                        "message": message["button"]["text"],
                        "message_id": message["id"],
                        "reply_to_message_id": reply_to_message_id,
                        "is_reply": is_reply,
                        "content_type": message_type,
                    }
                ).insert(ignore_permissions=True)
            else:
                frappe.get_doc(
                    {
                        "doctype": "WhatsApp Message",
                        "type": "Incoming",
                        "from": message["from"],
                        "message_id": message["id"],
                        "message": message[message_type].get(message_type),
                        "content_type": message_type,
                    }
                ).insert(ignore_permissions=True)

    else:
        changes = None
        try:
            changes = data["entry"][0]["changes"][0]
        except KeyError:
            changes = data["entry"]["changes"][0]
        update_status(changes)
    return


def send_response(receiver, message):
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

    data = {
        "messaging_product": "whatsapp",
        "to": receiver,
        "type": "text",
        "text": {"preview_url": True, "body": message},
    }

    try:
        response = make_post_request(
            f"{settings.url}/{settings.version}/{settings.phone_id}/messages",
            headers=headers,
            data=json.dumps(data),
        )
        message_id = response["messages"][0]["id"]
        print(f"Message id: {message_id}")

    except Exception as e:
        res = frappe.flags.integration_request.json()["error"]
        error_message = res.get("Error", res.get("message"))
        frappe.get_doc(
            {
                "doctype": "WhatsApp Notification Log",
                "template": "Text Message",
                "meta_data": frappe.flags.integration_request.json(),
            }
        ).insert(ignore_permissions=True)

        frappe.throw(msg=error_message, title=res.get("error_user_title", "Error"))


def update_status(data):
    """Update status hook."""
    if data.get("field") == "message_template_status_update":
        update_template_status(data["value"])

    elif data.get("field") == "messages":
        update_message_status(data["value"])


def update_template_status(data):
    """Update template status."""
    frappe.db.sql(
        """UPDATE `tabWhatsApp Templates`
		SET status = %(event)s
		WHERE id = %(message_template_id)s""",
        data,
    )


def update_message_status(data):
    """Update message status."""
    id = data["statuses"][0]["id"]
    status = data["statuses"][0]["status"]
    conversation = data["statuses"][0].get("conversation", {}).get("id")
    name = frappe.db.get_value("WhatsApp Message", filters={"message_id": id})

    doc = frappe.get_doc("WhatsApp Message", name)
    doc.status = status
    if conversation:
        doc.conversation_id = conversation
    doc.save(ignore_permissions=True)


@frappe.whitelist(allow_guest=True)
def get_production_data():
    prod_data = get_yearly_production_data()
    # return prod_data.data
    message = ""
    if prod_data:
        message += (
            "Total Produksi (update "
            + frappe.cstr(prod_data["additional_info"]["last_posting_date"])
            + " "
            + frappe.cstr(prod_data["additional_info"]["last_posting_time"])
            + ")\n"
        )
        for key in prod_data.data:

            message += "- " + key + " =\n"
            # for d, val in data.items():
            #     if d == "current_year":
            #         message ==
            message += (
                frappe.cstr(prod_data.data[key]["current_year"]["tonnage"])
                + " "
                + prod_data.data[key]["current_year"]["uom"]
                + "\n"
            )

    return message


@frappe.whitelist(allow_guest=True)
def get_yearly_production_data():

    filters = frappe._dict({"site_name": "Pusaka Tanah Persada", "year": "2024"})

    current_year_data = get_current_year_production_data(filters)

    if not current_year_data:
        return []

    prod_data = {}
    for i, i_items in current_year_data.items():
        item = get_mining_item(i)
        prod_data.setdefault(
            item.mining_item_name,
            {"tonnage": i_items["total_tonnage"], "uom": i_items["uom"]},
        )

    latest_datetime = get_last_production_datetime(filters)

    return frappe._dict(
        {
            "prod_data": prod_data,
            "last_posting_date": get_combine_datetime(
                latest_datetime.posting_date, latest_datetime.posting_time
            ),
        }
    )


def get_current_year_production_data(filters):
    prod = frappe.qb.DocType("Site Daily Production Entry")
    prod_detail = frappe.qb.DocType("Site Daily Production Entry Detail")

    sum_tonnage = Sum(prod_detail.tonnage_by_tf).as_("tonnage_by_tf")

    query = (
        frappe.qb.select(
            prod.site_name,
            prod.source_pit,
            Extract("month", prod.posting_date).as_("month"),
            Extract("year", prod.posting_date).as_("year"),
            prod_detail.mining_item_code,
            prod_detail.mining_item_name,
            sum_tonnage,
            prod_detail.tonnage_by_tf_uom,
        )
        .from_(prod_detail)
        .join(prod)
        .on(prod.name == prod_detail.parent)
        .where(
            (prod.docstatus == 1)
            & (prod.site_name == filters.get("site_name"))
            & (Extract("year", prod.posting_date) == filters.get("year"))
        )
        .orderby(prod.posting_date)
        .groupby(prod_detail.mining_item_code)
        .groupby(Extract("month", prod.posting_date))
    )

    data = query.run(as_dict=True)

    data_map = {}
    for d in data:
        data_map.setdefault(d.mining_item_code, {}).setdefault("tonnage_by_month", {})
        data_map[d.mining_item_code]["tonnage_by_month"][d.month] = d.tonnage_by_tf
        for m in range(1, 13):
            if m != d.month:
                data_map.setdefault(d.mining_item_code, {}).setdefault(
                    "tonnage_by_month", {}
                ).setdefault(m, 0)

    for j in data_map:
        total_tonnage = 0

        item = get_mining_item(j)
        for k, val in data_map[j]["tonnage_by_month"].items():
            total_tonnage += val

        data_map.setdefault(j, {}).setdefault("total_tonnage", total_tonnage)
        data_map.setdefault(j, {}).setdefault("uom", item.mining_item_uom)

    return data_map


def get_last_production_datetime(filters):
    prod = frappe.qb.DocType("Site Daily Production Entry")

    prod_query = (
        frappe.qb.select(
            prod.name,
            prod.site_name,
            prod.posting_date,
            prod.posting_time,
        )
        .from_(prod)
        .where(
            (prod.docstatus == 1)
            & (prod.site_name == filters.get("site_name"))
            & (Extract("year", prod.posting_date) == filters.get("year"))
        )
        .orderby(
            CombineDatetime(prod.posting_date, prod.posting_time), order=Order.desc
        )
        .limit(1)
    )
    p = prod_query.run(as_dict=True)
    return p[0]


def get_combine_datetime(posting_date, posting_time):
    import datetime

    if isinstance(posting_date, str):
        posting_date = getdate(posting_date)

    if isinstance(posting_time, str):
        posting_time = get_time(posting_time)

    if isinstance(posting_time, datetime.timedelta):
        posting_time = (datetime.datetime.min + posting_time).time()

    return datetime.datetime.combine(posting_date, posting_time).replace(microsecond=0)


def get_mining_item(item):
    mining_item = frappe.qb.DocType("Mining Item")
    mining_query = (
        frappe.qb.from_(mining_item)
        .select(
            mining_item.name, mining_item.mining_item_name, mining_item.mining_item_uom
        )
        .where(mining_item.name == item)
    )
    q = mining_query.run(as_dict=True)

    return q[0]
