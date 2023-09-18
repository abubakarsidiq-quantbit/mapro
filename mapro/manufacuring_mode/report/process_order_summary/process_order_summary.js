// Copyright (c) 2023, Pradip and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Process Order Summary"] = {
	"filters": [
		{
			label: __("Company"),
			fieldname: "company",
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1
		},
		{
			label: __("Process Name"),
			fieldname: "process_name",
			fieldtype: "Link",
			options: "Process Definition",
			reqd: 1
		},
		{
			label: __("Process Type"),
			fieldname: "process_name",
			fieldtype: "Link",
			options: "Process Type",
			reqd: 1
		},
		{
			label: __("status"),
			fieldname: "status",
			fieldtype: "Select",
			options: "Draft\nSubmitted\nIn Process\nCompleted\n	Cancelled",
			reqd: 1
		},

	]
};
