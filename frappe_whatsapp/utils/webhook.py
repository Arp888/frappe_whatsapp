"""Webhook."""

import calendar
import json
import time

import frappe
from frappe import _
import requests
from frappe.integrations.utils import make_post_request
from frappe.query_builder import Order
from frappe.query_builder.functions import CombineDatetime, Extract, Sum
from frappe.utils import (
    TypedDict,
    cstr,
    flt,
    get_link_to_form,
    get_time,
    getdate,
    nowdate,
    nowtime,
)
from hcapp.mine_production.api.v1.get_stockpile_balance import get_stockpile_balance
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

            if message_type["text"]["body"] in 



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

                if text.strip().lower() in ["in", "checkin", "out", "checkout", "masuk", "pulang"]:
                    url = frappe.conf.get("n8n_wa_webhook_url")

                    if not url:
                        frappe.throw(_("n8n webhook URL not configure."))

                    requests.post(
                        url,
                        json=data.get("entry", []),
                    )

                    return "Ok"


                if text.lower() == "hello":
                    msg = "Hi there! How can I help you?"
                    send_response(sender, msg)
                else:
                    filtered_text = filter_text_message(text)
                    if filtered_text:
                        keyword = filtered_text["keyword"]
                        filters = frappe._dict(
                            {
                                "site_name": filtered_text["site_name"],
                                "year": filtered_text["year"],
                            }
                        )
                        if keyword.lower() == "production":
                            prod = get_yearly_production_data(filters)
                            if prod:
                                prod_last_update = frappe.utils.format_datetime(
                                    prod.last_posting_date, "d MMM yyyy H:m"
                                )

                                msg = f"Total produksi (_update {prod_last_update}_)\n"
                                for key, val in prod.prod_data.items():
                                    tonnage = frappe.utils.fmt_money(val["tonnage"], 2)
                                    msg += f"- {key} = *{tonnage}* {val['uom']}\n"
                            else:
                                msg = "Production data is not available"
                        elif keyword.lower() == "stockpile":
                            sbal = get_stockpile_balance_report(filters)
                            if sbal:
                                last_update = frappe.utils.format_datetime(
                                    sbal["last_update"], "d MMM yyyy H:m"
                                )
                                msg = f"Stockpile balance (_update {last_update}_)\n"
                                for sb in sbal["balance"]:
                                    msg += f"- {sb} = "
                                    for dt in sbal["balance"][sb]:
                                        qty_survey = frappe.utils.fmt_money(
                                            sbal["balance"][sb][dt]["qty_by_survey"], 2
                                        )
                                        msg += f"*{qty_survey}* {sbal['balance'][sb][dt]['uom']}\n"
                            else:
                                msg = "Stobkpile balance data is not available"
                        else:
                            msg = "Please type your keyword with correct format (eg: 'production ptp 2025' or 'stockpile ptp 2025')"
                    else:
                        msg = "Please type your keyword with correct format (eg: 'production ptp 2025' or 'stockpile ptp 2025')"

                    send_response(sender, msg)

            elif message_type == "location":
                frappe.get_doc(
                    {
                        "doctype": "WhatsApp Message",
                        "type": "Incoming",
                        "from": message["from"],
                        "message": message["location"],
                        "message_id": message["id"],
                        "reply_to_message_id": reply_to_message_id,
                        "is_reply": is_reply,
                        "content_type": message_type,
                    }
                ).insert(ignore_permissions=True)

                url = frappe.conf.get("n8n_wa_webhook_url")

                if not url:
                    frappe.throw(_("n8n webhook URL not configure."))

                requests.post(
                    url,
                    json=data.get("entry", []),
                )

                return "Ok"


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
        "text": {"preview_url": False, "body": message},
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


class StockpileBalanceFilter(TypedDict):
    site_name: str | None
    from_date: str
    to_date: str
    mining_item_code: str | None
    stockpile_name: str | None
    year: str | None


SLEntry = dict[str, frappe.Any]


@frappe.whitelist(allow_guest=True)
def check_stock():
    filters = frappe._dict({"site_name": "Pusaka Tanah Persada", "year": "2024"})
    sbal = get_stockpile_balance_report(filters)
    msg = ""
    if sbal:
        last_update = frappe.utils.format_datetime(
            sbal["last_update"], "d MMM yyyy H:m"
        )
        msg = f"Stockpile balance (_update {last_update}_)\n"
        for sb in sbal["balance"]:
            msg += f"- {sb} = "
            for dt in sbal["balance"][sb]:
                qty_survey = frappe.utils.fmt_money(
                    sbal["balance"][sb][dt]["qty_by_survey"], 2
                )
                msg += f"*{qty_survey}* {sbal['balance'][sb][dt]['uom']}\n"

    return msg


@frappe.whitelist(allow_guest=True)
def filter_text_message(text):
    import re

    text_lower = text.lower()
    text_array = text_lower.split(" ")
    text_array_filter = [var for var in text_array if var]
    if len(text_array_filter) < 3:
        return {}

    keyword = text_array_filter[0]
    site_name = text_array_filter[1]
    year = text_array_filter[2]

    pattern_str = r"^\d{4}$"
    check_year_format = re.match(pattern_str, year)

    if not site_name or not year or not check_year_format:
        return {}

    site = get_site_name(site_name)

    if not site:
        return {}

    return {"keyword": keyword, "site_name": site[0].name, "year": year}


@frappe.whitelist(allow_guest=True)
def get_stockpile_balance_report(filters):
    # filters = frappe._dict({"site_name": "Pusaka Tanah Persada", "year": "2024"})
    stockpile_balances = get_stockpile_balance(filters)
    data_map = {}
    if stockpile_balances.stp_balance:
        data_map = {
            "balance": stockpile_balances.stp_balance,
            "last_update": stockpile_balances.additional_info[
                "last_stockpile_reco_posting_datetime"
            ],
        }

    return data_map


@frappe.whitelist(allow_guest=True)
def get_production_data(filters):
    prod = get_yearly_production_data(filters)
    # return prod_data.data
    msg = ""
    if prod:
        msg = f"*Total produksi (update {prod.last_posting_date})*\n"
        for key, val in prod.prod_data.items():
            msg += f"- {key} = {val['tonnage']} {val['uom']}\n"

    return msg


@frappe.whitelist(allow_guest=True)
def get_yearly_production_data(filters):

    # filters = frappe._dict({"site_name": "PT Pusaka Tanah Persada", "year": "2025"})

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


def get_site_name(item):
    site_location = frappe.qb.DocType("Site Location")
    query = (
        frappe.qb.from_(site_location)
        .select(site_location.name, site_location.site_name, site_location.site_abbr)
        .where(site_location.site_abbr == item)
    )
    q = query.run(as_dict=True)

    return q
