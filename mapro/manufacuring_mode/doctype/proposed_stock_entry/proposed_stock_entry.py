# Copyright (c) 2024, Pradip and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document
from frappe.utils import cint, comma_or, cstr, flt, format_time, formatdate, getdate, nowdate

import erpnext
from erpnext.accounts.general_ledger import process_gl_map
from erpnext.controllers.taxes_and_totals import init_landed_taxes_and_totals
from erpnext.manufacturing.doctype.bom.bom import (
	add_additional_cost,
	get_op_cost_from_sub_assemblies,
	get_scrap_items_from_sub_assemblies,
	validate_bom_no,
)
from erpnext.setup.doctype.brand.brand import get_brand_defaults
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.stock.doctype.batch.batch import get_batch_no, get_batch_qty, set_batch_nos
from erpnext.stock.doctype.item.item import get_item_defaults
from erpnext.stock.doctype.serial_no.serial_no import (
	get_serial_nos,
	update_serial_nos_after_submit,
)
from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import (
	OpeningEntryAccountError,
)
from erpnext.stock.get_item_details import (
	get_barcode_data,
	get_bin_details,
	get_conversion_factor,
	get_default_cost_center,
	get_reserved_qty_for_so,
)
from erpnext.stock.stock_ledger import NegativeStockError, get_previous_sle, get_valuation_rate
from erpnext.stock.utils import get_bin, get_incoming_rate

class ProposedStockEntry(Document):
	def before_submit(self):
		po = frappe.get_doc("Process Order",self.process_order)
		if self.stock_entry_type == "Material Transfer for Manufacture":
			stock_entry = frappe.new_doc("Stock Entry")
			stock_entry.custom_proposed_stock_entry = self.name
			stock_entry.purpose = "Material Transfer for Manufacture"
			stock_entry.stock_entry_type = "Material Transfer for Manufacture"
			stock_entry.process_order = self.process_order
			stock_entry.from_warehouse = po.src_warehouse
			stock_entry.to_warehouse = po.fg_warehouse
			for se in self.items:
				stock_entry.append("items",{
					's_warehouse': se.s_warehouse,
					't_warehouse': se.t_warehouse,
					'item_name': se.item_name,
					'qty': se.qty,
					'item_code': se.item_code,
					'uom': se.uom,
					'stock_uom': se.stock_uom,
					'expense_account': se.expense_account,
					'cost_center': se.cost_center,
					'transfer_qty': se.transfer_qty,
					'conversion_factor': 1.00,
				})
			
			stock_entry.total_outgoing_value = self.total_outgoing_value
			stock_entry.total_difference_ = self.total_difference_
			stock_entry.total_incoming_value = self.total_incoming_value
			stock_entry.value_difference = self.value_difference
			stock_entry.custom_quantity_difference_ = self.custom_quantity_difference_
			stock_entry.custom_in_qty_kg = self.custom_in_qty_kg

			for op in self.additional_costs:
				stock_entry.append("additional_costs",{
					'expense_account': op.expense_account,
					'amount': op.amount,
					'description': 'None'
				})
			stock_entry.total_additional_costs = sum(tot_op.amount for tot_op in self.additional_costs)
			stock_entry.insert()
			stock_entry.save()
			stock_entry.submit()

		if self.stock_entry_type == "Manufacture":
			for d in range(1,len(self.items)):
				if self.items[d].is_finished_item:
					stock_entry = frappe.new_doc("Stock Entry")
					stock_entry.custom_proposed_stock_entry = self.name
					stock_entry.purpose = "Manufacture"
					stock_entry.stock_entry_type = "Manufacture"
					stock_entry.set_posting_time = True
					stock_entry.posting_date = self.posting_date
					if self.items[0].cost_center:
						stock_entry.append(
							"items",
							{
								"item_code": self.items[0].item_code,
								"qty": ((self.items[0].qty)/(po.finished_products_qty))*self.items[d].qty,
								"uom": self.items[0].uom,
								"s_warehouse": po.fg_warehouse,
								"batch_no": self.items[0].batch_no,
								"cost_center": self.items[0].cost_center
							},
						)
					else:
						frappe.throw("Cost Center Is Mandatory")
					if self.items[d].cost_center:
						stock_entry.append(
							"items",
							{
								"item_code": self.items[d].item_code,
								"qty": self.items[d].qty,
								"uom": 'KGS',
								"t_warehouse": po.wip_warehouse,
								"batch_no": self.items[d].batch_no,
								"is_finished_item": True,
								"cost_center": self.items[d].cost_center
							},
						)
					else:
						frappe.throw("Cost Center Is Mandatory")
					for k in self.get("additional_costs"):
						stock_entry.append("additional_costs",{
								"expense_account": k.expense_account,
								"description": k.description,
								"amount": (k.amount * self.items[d].qty)/po.finished_products_qty,
							},
						)
					stock_entry.cost_center = self.cost_center
					stock_entry.total_additional_costs = sum(tot_op.amount for tot_op in stock_entry.additional_costs)
					stock_entry.insert()
					stock_entry.save()
					stock_entry.submit()
			# 	if self.items[d].is_scrap_item:
			# 		stock_entry = frappe.new_doc("Stock Entry")
			# 		stock_entry.custom_proposed_stock_entry = self.name
			# 		stock_entry.purpose = "Manufacture"
			# 		stock_entry.stock_entry_type = "Manufacture"
			# 		stock_entry.set_posting_time = True
			# 		stock_entry.posting_date = self.posting_date
			# 		stock_entry.append(
			# 			"items",
			# 			{
			# 				"item_code": self.items[0].item_code,
			# 				"qty": self.items[0].qty,
			# 				"uom": self.items[0].uom,
			# 				"s_warehouse": po.fg_warehouse,
			# 				"batch_no": self.items[0].batch_no
			# 			},
			# 		)
			# 		stock_entry.append(
			# 			"items",
			# 			{
			# 				"item_code": self.items[d].item_code,
			# 				"qty": self.items[d].qty,
			# 				"uom": 'KGS',
			# 				"t_warehouse": po.wip_warehouse,
			# 				"batch_no": self.items[d].batch_no,
			# 				"is_scrap_item": True
			# 			},
			# 		)	
			# 		for k in self.get("additional_costs"):
			# 			stock_entry.append("additional_costs",{
			# 					"expense_account": k.expense_account,
			# 					"description": k.description,
			# 					"amount": (k.amount * self.items[d].qty)/po.finished_products_qty,
			# 				},
			# 			)
			# 		stock_entry.total_additional_costs = sum(tot_op.amount for tot_op in stock_entry.additional_costs)
			# 		stock_entry.insert()
			# 		stock_entry.save()
			# 		stock_entry.submit()
			# frappe.msgprint("Manufacture entry successfully inserted")


			# for d in self.get("in_items"):
			# 	doc = frappe.new_doc("Stock Entry")
			# 	doc.stock_entry_type = "Manufacture"
			# 	doc.set_posting_time = True
			# 	doc.posting_date = self.posting_date
			# 	for j in self.get("out_item"):
			# 		if j.ref_challan == d.ref_challan:
			# 			doc.append(
			# 				"items",
			# 				{
			# 					"item_code": j.raw_item_code,
			# 					"qty": j.production_quantity,
			# 					"uom": j.uom,
			# 					"s_warehouse": self.source_warehouse,
			# 					"batch_no": d.batch_id
			# 				},
			# 			)
			# 	doc.append(
			# 		"items",
			# 		{
			# 			"item_code": d.finished_item,
			# 			"qty": d.qty,
			# 			"uom": 'KGS',
			# 			"t_warehouse": self.wip_warehouse,
			# 			"is_finished_item": True
			# 		},
			# 	)	
			# 	for k in self.get("operation_cost"):
			# 		doc.append("additional_costs",{
			# 				"expense_account": k.operations,
			# 				"description": k.operations,
			# 				"amount": (k.cost * d.qty)/self.finished_products_qty,
			# 			},
			# 		)
			# 	doc.custom_in_subcontracting = self.name
			# 	doc.insert()
			# 	doc.save()
			# 	doc.submit()
			# 	frappe.msgprint("Manufacture entry successfully inserted")

	@frappe.whitelist()
	def get_stock_and_rate(self):
		"""
		Updates rate and availability of all the items.
		Called from Update Rate and Availability button.
		"""
		self.set_work_order_details()
		self.set_transfer_qty()
		self.set_actual_qty()
		self.calculate_rate_and_amount()
	
	def calculate_rate_and_amount(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		self.set_basic_rate(reset_outgoing_rate, raise_error_if_no_rate)
		init_landed_taxes_and_totals(self)
		self.distribute_additional_costs()
		self.update_valuation_rate()
		self.set_total_incoming_outgoing_value()
		self.set_total_amount()
	
	def set_basic_rate(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		"""
		Set rate for outgoing, scrapped and finished items
		"""
		# Set rate for outgoing items
		outgoing_items_cost = self.set_rate_for_outgoing_items(reset_outgoing_rate, raise_error_if_no_rate)
		finished_item_qty = sum(d.transfer_qty for d in self.items if d.is_finished_item)

		items = []
		# Set basic rate for incoming items
		for d in self.get("items"):
			if d.s_warehouse or d.set_basic_rate_manually:
				continue

			if d.allow_zero_valuation_rate:
				d.basic_rate = 0.0
				items.append(d.item_code)

			elif d.is_finished_item:
				if self.purpose == "Manufacture":
					d.basic_rate = self.get_basic_rate_for_manufactured_item(
						finished_item_qty, outgoing_items_cost
					)
				elif self.purpose == "Repack":
					d.basic_rate = self.get_basic_rate_for_repacked_items(d.transfer_qty, outgoing_items_cost)

			if not d.basic_rate and not d.allow_zero_valuation_rate:
				d.basic_rate = get_valuation_rate(
					d.item_code,
					d.t_warehouse,
					self.doctype,
					self.name,
					d.allow_zero_valuation_rate,
					currency=erpnext.get_company_currency(self.company),
					company=self.company,
					raise_error_if_no_rate=raise_error_if_no_rate,
					batch_no=d.batch_no,
				)

			# do not round off basic rate to avoid precision loss
			d.basic_rate = flt(d.basic_rate)
			d.basic_amount = flt(flt(d.transfer_qty) * flt(d.basic_rate), d.precision("basic_amount"))

		if items:
			message = ""

			if len(items) > 1:
				message = (
					"Items rate has been updated to zero as Allow Zero Valuation Rate is checked for the following items: {0}"
				).format(", ".join(frappe.bold(item) for item in items))
			else:
				message = (
					"Item rate has been updated to zero as Allow Zero Valuation Rate is checked for item {0}"
				).format(frappe.bold(items[0]))

			frappe.msgprint(message, alert=True)
	
	def set_rate_for_outgoing_items(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
		outgoing_items_cost = 0.0
		for d in self.get("items"):
			if d.s_warehouse:
				if reset_outgoing_rate:
					args = self.get_args_for_incoming_rate(d)
					rate = get_incoming_rate(args, raise_error_if_no_rate)
					if rate > 0:
						d.basic_rate = rate

				d.basic_amount = flt(flt(d.transfer_qty) * flt(d.basic_rate), d.precision("basic_amount"))
				if not d.t_warehouse:
					outgoing_items_cost += flt(d.basic_amount)

		return outgoing_items_cost
	
	def get_args_for_incoming_rate(self, item):
		return frappe._dict(
			{
				"item_code": item.item_code,
				"warehouse": item.s_warehouse or item.t_warehouse,
				"posting_date": self.posting_date,
				"posting_time": self.posting_time,
				"qty": item.s_warehouse and -1 * flt(item.transfer_qty) or flt(item.transfer_qty),
				"serial_no": item.serial_no,
				"batch_no": item.batch_no,
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"company": self.company,
				"allow_zero_valuation": item.allow_zero_valuation_rate,
			}
		)
	
	def set_total_amount(self):
		self.total_amount = None
		if self.purpose not in ["Manufacture", "Repack"]:
			self.total_amount = sum([flt(item.amount) for item in self.get("items")])
	
	def set_total_incoming_outgoing_value(self):
		self.total_incoming_value = self.total_outgoing_value = 0.0
		for d in self.get("items"):
			if d.t_warehouse:
				self.total_incoming_value += flt(d.amount)
			if d.s_warehouse:
				self.total_outgoing_value += flt(d.amount)

		self.value_difference = self.total_incoming_value - self.total_outgoing_value
	
	def update_valuation_rate(self):
		for d in self.get("items"):
			if d.transfer_qty:
				d.amount = flt(flt(d.basic_amount) + flt(d.additional_cost), d.precision("amount"))
				# Do not round off valuation rate to avoid precision loss
				d.valuation_rate = flt(d.basic_rate) + (flt(d.additional_cost) / flt(d.transfer_qty))

	def distribute_additional_costs(self):
		# If no incoming items, set additional costs blank
		if not any(d.item_code for d in self.items if d.t_warehouse):
			self.additional_costs = []

		self.total_additional_costs = sum(flt(t.base_amount) for t in self.get("additional_costs"))

		if self.purpose in ("Repack", "Manufacture"):
			incoming_items_cost = sum(flt(t.basic_amount) for t in self.get("items") if t.is_finished_item)
		else:
			incoming_items_cost = sum(flt(t.basic_amount) for t in self.get("items") if t.t_warehouse)

		if not incoming_items_cost:
			return

		for d in self.get("items"):
			if self.purpose in ("Repack", "Manufacture") and not d.is_finished_item:
				d.additional_cost = 0
				continue
			elif not d.t_warehouse:
				d.additional_cost = 0
				continue
			d.additional_cost = (flt(d.basic_amount) / incoming_items_cost) * self.total_additional_costs

	def set_actual_qty(self):
		from erpnext.stock.stock_ledger import is_negative_stock_allowed

		for d in self.get("items"):
			allow_negative_stock = is_negative_stock_allowed(item_code=d.item_code)
			previous_sle = get_previous_sle(
				{
					"item_code": d.item_code,
					"warehouse": d.s_warehouse or d.t_warehouse,
					"posting_date": self.posting_date,
					"posting_time": self.posting_time,
				}
			)

			# get actual stock at source warehouse
			d.actual_qty = previous_sle.get("qty_after_transaction") or 0

			# validate qty during submit
			if (
				d.docstatus == 1
				and d.s_warehouse
				and not allow_negative_stock
				and flt(d.actual_qty, d.precision("actual_qty"))
				< flt(d.transfer_qty, d.precision("actual_qty"))
			):
				frappe.throw(
					(
						"Row {0}: Quantity not available for {4} in warehouse {1} at posting time of the entry ({2} {3})"
					).format(
						d.idx,
						frappe.bold(d.s_warehouse),
						formatdate(self.posting_date),
						format_time(self.posting_time),
						frappe.bold(d.item_code),
					)
					+ "<br><br>"
					+ ("Available quantity is {0}, you need {1}").format(
						frappe.bold(flt(d.actual_qty, d.precision("actual_qty"))), frappe.bold(d.transfer_qty)
					),
					NegativeStockError,
					title=("Insufficient Stock"),
				)

	def set_work_order_details(self):
		if not getattr(self, "pro_doc", None):
			self.pro_doc = frappe._dict()

		if self.work_order:
			# common validations
			if not self.pro_doc:
				self.pro_doc = frappe.get_doc("Work Order", self.work_order)

			if self.pro_doc:
				self.bom_no = self.pro_doc.bom_no
			else:
				# invalid work order
				self.work_order = None
	
	def set_transfer_qty(self):
		for item in self.get("items"):
			if not flt(item.qty):
				frappe.throw(("Row {0}: Qty is mandatory").format(item.idx), title=("Zero quantity"))
			if not flt(item.conversion_factor):
				frappe.throw(("Row {0}: UOM Conversion Factor is mandatory").format(item.idx))
			item.transfer_qty = flt(
				flt(item.qty) * flt(item.conversion_factor), self.precision("transfer_qty", item)
			)
			if not flt(item.transfer_qty):
				frappe.throw(("Row {0}: Qty in Stock UOM can not be zero.").format(item.idx), title=("Zero quantity"))

	@frappe.whitelist()
	def get_item_details(self, args=None, for_update=False):
		item = frappe.db.sql(
			"""select i.name, i.stock_uom, i.description, i.image, i.item_name, i.item_group,
				i.has_batch_no, i.sample_quantity, i.has_serial_no, i.allow_alternative_item,
				id.expense_account, id.buying_cost_center
			from `tabItem` i LEFT JOIN `tabItem Default` id ON i.name=id.parent and id.company=%s
			where i.name=%s
				and i.disabled=0
				and (i.end_of_life is null or i.end_of_life<'1900-01-01' or i.end_of_life > %s)""",
			(self.company, args.get("item_code"), nowdate()),
			as_dict=1,
		)
		# frappe.throw(str(item))
		if not item:
			frappe.throw(("Item {0} is not active or end of life has been reached").format(args.get("item_code")))

		item = item[0]
		item_group_defaults = get_item_group_defaults(item.name, self.company)
		brand_defaults = get_brand_defaults(item.name, self.company)

		ret = frappe._dict(
			{
				"uom": item.stock_uom,
				"stock_uom": item.stock_uom,
				"description": item.description,
				"image": item.image,
				"item_name": item.item_name,
				"cost_center": get_default_cost_center(
					args, item, item_group_defaults, brand_defaults, self.company
				),
				"qty": args.get("qty"),
				"transfer_qty": args.get("qty"),
				"conversion_factor": 1,
				"batch_no": "",
				"actual_qty": 0,
				"basic_rate": 0,
				"serial_no": "",
				"has_serial_no": item.has_serial_no,
				"has_batch_no": item.has_batch_no,
				"sample_quantity": item.sample_quantity,
				"expense_account": item.expense_account,
			}
		)

		if self.purpose == "Send to Subcontractor":
			ret["allow_alternative_item"] = item.allow_alternative_item

		# update uom
		if args.get("uom") and for_update:
			ret.update(get_uom_details(args.get("item_code"), args.get("uom"), args.get("qty")))

		if self.purpose == "Material Issue":
			ret["expense_account"] = item.get("expense_account") or item_group_defaults.get("expense_account")

		for company_field, field in {
			"stock_adjustment_account": "expense_account",
			"cost_center": "cost_center",
		}.items():
			if not ret.get(field):
				ret[field] = frappe.get_cached_value("Company", self.company, company_field)

		args["posting_date"] = self.posting_date
		args["posting_time"] = self.posting_time

		stock_and_rate = get_warehouse_details(args) if args.get("warehouse") else {}
		ret.update(stock_and_rate)

		# automatically select batch for outgoing item
		if (
			args.get("s_warehouse", None)
			and args.get("qty")
			and ret.get("has_batch_no")
			and not args.get("batch_no")
		):
			args.batch_no = get_batch_no(args["item_code"], args["s_warehouse"], args["qty"])

		if (
			self.purpose == "Send to Subcontractor"
			and self.get(self.subcontract_data.order_field)
			and args.get("item_code")
		):
			subcontract_items = frappe.get_all(
				self.subcontract_data.order_supplied_items_field,
				{
					"parent": self.get(self.subcontract_data.order_field),
					"rm_item_code": args.get("item_code"),
				},
				"main_item_code",
			)

			if subcontract_items and len(subcontract_items) == 1:
				ret["subcontracted_item"] = subcontract_items[0].main_item_code

		barcode_data = get_barcode_data(item_code=item.name)
		if barcode_data and len(barcode_data.get(item.name)) == 1:
			ret["barcode"] = barcode_data.get(item.name)[0]

		return ret
	
@frappe.whitelist()
def get_warehouse_details(args):
	if isinstance(args, str):
		args = json.loads(args)

	args = frappe._dict(args)

	ret = {}
	if args.warehouse and args.item_code:
		args.update(
			{
				"posting_date": args.posting_date,
				"posting_time": args.posting_time,
			}
		)
		ret = {
			"actual_qty": get_previous_sle(args).get("qty_after_transaction") or 0,
			"basic_rate": get_incoming_rate(args),
		}
	return ret

@frappe.whitelist()
def get_uom_details(item_code, uom, qty):
	"""Returns dict `{"conversion_factor": [value], "transfer_qty": qty * [value]}`
	:param args: dict with `item_code`, `uom` and `qty`"""
	conversion_factor = get_conversion_factor(item_code, uom).get("conversion_factor")

	if not conversion_factor:
		frappe.msgprint(("UOM conversion factor required for UOM: {0} in Item: {1}").format(uom, item_code))
		ret = {"uom": ""}
	else:
		ret = {
			"conversion_factor": flt(conversion_factor),
			"transfer_qty": flt(qty) * flt(conversion_factor),
		}
	return ret