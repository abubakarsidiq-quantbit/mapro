# Copyright (c) 2023, Pradip and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, today


def execute(filters=None):
	columns, data = [], []
	# return columns, data
	data = get_data(filters)
	columns = get_columns(filters)
	# chart_data = get_chart_data(data, filters)
	# return columns, data, None, chart_data

def get_data(filters):
	query_filters = {"docstatus": ("<", 2)}

	fields = [
		"name",
		"status",
		"process_name",
		"workstation",
		"process_type",
		"creation",
	]

	data = frappe.get_all(
		"Process Order", fields=fields, filters=query_filters, debug=1
	)

def get_columns(filters):
	columns = [
		{
			"label": _("Id"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Process Order",
			"width": 100,
		},
	]

	if not filters.get("status"):
		columns.append(
			{"label": _("Status"), "fieldname": "status", "width": 100},
		)

	columns.extend(
		[
			{
				"label": _("Process Name"),
				"fieldname": "process_name",
				"fieldtype": "Link",
				"options": "Process Definition",
				"width": 130,
			},
			{
				"label": _("Process Type"),
				"fieldname": "process_type",
				"fieldtype": "Link",
				"options": "Process Type",
				"width": 130,
			},
		]
	)
