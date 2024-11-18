# Copyright (c) 2024, Pradip and contributors
# For license information, please see license.txt

import frappe
import json
from collections import defaultdict
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
from frappe.utils import cint, flt, get_time, now_datetime
from frappe import _
from erpnext.controllers.stock_controller import StockController

class FinishedGoodError(frappe.ValidationError):
	pass

class ProposedStockEntry(StockController):
	def on_submit(self):
		po = frappe.get_doc("Process Order", self.batch_order)
		if self.stock_entry_type == "Material Transfer for Manufacture":
			stock_entry = frappe.new_doc("Stock Entry")
			stock_entry.set_posting_time = True  
			stock_entry.posting_date = self.posting_date
			stock_entry.posting_time = self.posting_time
			stock_entry.naming_series = '-'.join(self.naming_series.split('-')[1:])
			stock_entry.custom_proposed_stock_entry = self.name
			stock_entry.purpose = "Material Transfer for Manufacture"
			stock_entry.stock_entry_type = "Material Transfer for Manufacture"
			stock_entry.process_order = self.custom_job_offer
			stock_entry.custom_job_offer = self.batch_order
			stock_entry.from_warehouse = po.src_warehouse
			stock_entry.to_warehouse = po.fg_warehouse
			for se in self.items:
				stock_entry.append("items", {
					's_warehouse': se.s_warehouse,
					't_warehouse': se.t_warehouse,
					'item_name': se.item_name,
					'qty': se.qty,
					'item_code': se.item_code,
					'uom': se.uom,
					'batch_no': se.batch_no,
					'stock_uom': se.stock_uom,
					'expense_account': se.expense_account,
					'cost_center': se.cost_center,
					'transfer_qty': se.transfer_qty,
					'conversion_factor': 1.00,
					'cost_center': self.cost_center
				})
			stock_entry.total_outgoing_value = self.total_outgoing_value
			stock_entry.total_difference_ = self.total_difference_
			stock_entry.total_incoming_value = self.total_incoming_value
			stock_entry.value_difference = self.value_difference
			stock_entry.custom_quantity_difference_ = self.custom_quantity_difference_
			stock_entry.custom_in_qty_kg = self.custom_in_qty_kg
			for op in self.additional_costs:
				stock_entry.append("additional_costs", {
					'expense_account': op.expense_account,
					'amount': op.amount,
					'description': 'None'
				})
			stock_entry.cost_center = self.cost_center
			stock_entry.total_additional_costs = sum(tot_op.amount for tot_op in self.additional_costs)

			stock_entry.insert()
			stock_entry.save()
			stock_entry.submit()

		if self.stock_entry_type == "Manufacture":
			tot_qty, tot_basic_amt = 0, 0
			for i in self.items:
				if i.t_warehouse:
					tot_qty += i.qty
					tot_basic_amt +=  i.basic_amount
			for d in range(1, len(self.items)):
				if ((self.items[d].basic_amount/tot_basic_amt) * self.items[0].qty) > 0:
					stock_entry = frappe.new_doc("Stock Entry")
					stock_entry.set_posting_time = True  
					stock_entry.posting_date = self.posting_date
					stock_entry.posting_time = self.posting_time
					stock_entry.naming_series = '-'.join(self.naming_series.split('-')[1:])
					stock_entry.custom_proposed_stock_entry = self.name
					stock_entry.purpose = "Manufacture"
					stock_entry.stock_entry_type = "Manufacture"
					stock_entry.process_order = self.custom_job_offer
					if self.items[0].cost_center:
						stock_entry.append("items", {
							"item_code": self.items[0].item_code,
							"qty": (self.items[d].basic_amount/tot_basic_amt) * self.items[0].qty,
							"uom": self.items[0].uom,
							"s_warehouse": self.items[0].s_warehouse,
							"batch_no": self.items[0].batch_no,
							"cost_center": self.items[0].cost_center
						})
					else:
						frappe.throw("Cost Center Is Mandatory")

					if self.items[d].cost_center:
						stock_entry.append("items", {
							"item_code": self.items[d].item_code,
							"qty": self.items[d].qty,
							"uom": 'KGS',
							"t_warehouse": po.wip_warehouse,
							"batch_no": self.items[d].batch_no,
							"is_finished_item": True,
							"cost_center": self.items[d].cost_center
						})
					else:
						frappe.throw("Cost Center Is Mandatory")

					for k in self.get("additional_costs"):
						stock_entry.append("additional_costs", {
							"expense_account": k.expense_account,
							"description": k.description,
							"amount": k.amount * (self.items[d].basic_amount/tot_basic_amt),
						})

					stock_entry.cost_center = self.cost_center
					stock_entry.total_additional_costs = sum(tot_op.amount for tot_op in stock_entry.additional_costs)

					stock_entry.insert()
					stock_entry.save()
					stock_entry.submit()


	def before_save(self):
		self.calculate_rate_and_amount()
		total_sale_value, material_amount, material_qty, total_basic_value, incom = 0, 0, 0, 0, 0
		for itm in self.items:
			if itm.s_warehouse:
				material_qty += itm.qty
				material_amount += itm.amount
		for itm in self.items:
			if itm.is_finished_item:
				itm.sales_value = itm.qty * itm.manufacturing_rate
		for itm in self.items:
			if itm.is_finished_item:
				total_sale_value += itm.sales_value
		for itm in self.items:
			if itm.is_finished_item:
				itm.yeild = (itm.qty/material_qty) * 100
				itm.basic_amount = (itm.sales_value / total_sale_value) * material_amount
		for itm in self.items:
			if itm.is_finished_item:
				total_basic_value += itm.basic_amount
		for itm in self.items:
			if itm.is_finished_item:
				itm.additional_cost = (itm.basic_amount/total_basic_value) * self.total_additional_costs
				itm.total_cost = itm.additional_cost + itm.basic_amount
				itm.valuation_rate = itm.total_cost / itm.qty
				itm.amount = itm.valuation_rate * itm.qty
				incom += itm.amount
				itm.basic_rate = itm.basic_amount / itm.qty

		self.total_outgoing_value = material_amount
		self.total_incoming_value = incom
		self.value_difference = incom - material_amount

	@frappe.whitelist()
	def diffqty(self):
		if self.stock_entry_type == 'Manufacture':
			tqdif = float(0)
			sqdiff = float(0)
			for s in self.get('items'):
				t_warehouse_str = str(s.t_warehouse)
				s_warehouse_str = str(s.s_warehouse)
				if t_warehouse_str == "None" or t_warehouse_str == "":
					tqdif += s.qty
				if s_warehouse_str == "None" or s_warehouse_str == "":
					sqdiff += s.qty
			self.custom_quantity_difference_ = tqdif - sqdiff
			opp =0
			for s in self.get('items'):
				t_warehouse_str = str(s.t_warehouse)
				if t_warehouse_str == "None" or t_warehouse_str == "" :
					opp += s.qty
			self.custom_in_qty_kg = self.total_additional_costs / float(opp)

	def validate(self):
		self.pro_doc = frappe._dict()
		if self.work_order:
			self.pro_doc = frappe.get_doc("Work Order", self.work_order)

		self.validate_posting_time()
		self.validate_purpose()
		self.validate_item()
		self.validate_customer_provided_item()
		self.validate_qty()
		self.set_transfer_qty()
		self.validate_uom_is_integer("uom", "qty")
		self.validate_uom_is_integer("stock_uom", "transfer_qty")
		self.validate_warehouse()
		self.validate_work_order()
		self.validate_bom()
		self.set_process_loss_qty()
		self.validate_purchase_order()
		self.validate_subcontracting_order()

		if self.purpose in ("Manufacture", "Repack"):
			self.mark_finished_and_scrap_items()
			self.validate_finished_goods()

		self.validate_with_material_request()
		self.validate_batch()
		self.validate_inspection()
		self.validate_fg_completed_qty()
		self.validate_difference_account()
		self.set_job_card_data()
		self.validate_job_card_item()
		self.set_purpose_for_stock_entry()
		self.clean_serial_nos()
		self.validate_duplicate_serial_no()

		if not self.from_bom:
			self.fg_completed_qty = 0.0

		if self._action == "submit":
			self.make_batches("t_warehouse")
		else:
			set_batch_nos(self, "s_warehouse")

		self.validate_serialized_batch()
		self.set_actual_qty()
		# self.calculate_rate_and_amount()
		self.validate_putaway_capacity()

		if not self.get("purpose") == "Manufacture":
			self.reset_default_field_value("from_warehouse", "items", "s_warehouse")
			self.reset_default_field_value("to_warehouse", "items", "t_warehouse")
   
	def reset_default_field_value(self, default_field: str, child_table: str, child_table_field: str):
		"""Reset "Set default X" fields on forms to avoid confusion.

		example:
		        doc = {
		                "set_from_warehouse": "Warehouse A",
		                "items": [{"from_warehouse": "warehouse B"}, {"from_warehouse": "warehouse A"}],
		        }
		        Since this has dissimilar values in child table, the default field will be erased.

		        doc.reset_default_field_value("set_from_warehouse", "items", "from_warehouse")
		"""
		child_table_values = set()

		for row in self.get(child_table):
			child_table_values.add(row.get(child_table_field))

		if len(child_table_values) > 1:
			self.set(default_field, None)
   
	def validate_putaway_capacity(self):
		# if over receipt is attempted while 'apply putaway rule' is disabled
		# and if rule was applied on the transaction, validate it.
		from erpnext.stock.doctype.putaway_rule.putaway_rule import get_available_putaway_capacity

		valid_doctype = self.doctype in (
			"Purchase Receipt",
			"Stock Entry",
			"Purchase Invoice",
			"Stock Reconciliation",
		)

		if not frappe.get_all("Putaway Rule", limit=1):
			return

		if self.doctype == "Purchase Invoice" and self.get("update_stock") == 0:
			valid_doctype = False

		if valid_doctype:
			rule_map = defaultdict(dict)
			for item in self.get("items"):
				warehouse_field = "t_warehouse" if self.doctype == "Stock Entry" else "warehouse"
				rule = frappe.db.get_value(
					"Putaway Rule",
					{"item_code": item.get("item_code"), "warehouse": item.get(warehouse_field)},
					["name", "disable"],
					as_dict=True,
				)
				if rule:
					if rule.get("disabled"):
						continue  # dont validate for disabled rule

					if self.doctype == "Stock Reconciliation":
						stock_qty = flt(item.qty)
					else:
						stock_qty = (
							flt(item.transfer_qty) if self.doctype == "Stock Entry" else flt(item.stock_qty)
						)

					rule_name = rule.get("name")
					if not rule_map[rule_name]:
						rule_map[rule_name]["warehouse"] = item.get(warehouse_field)
						rule_map[rule_name]["item"] = item.get("item_code")
						rule_map[rule_name]["qty_put"] = 0
						rule_map[rule_name]["capacity"] = get_available_putaway_capacity(rule_name)
					rule_map[rule_name]["qty_put"] += flt(stock_qty)

			for rule, values in rule_map.items():
				if flt(values["qty_put"]) > flt(values["capacity"]):
					message = self.prepare_over_receipt_message(rule, values)
					frappe.throw(msg=message, title=_("Over Receipt"))
   
	def validate_serialized_batch(self):
		from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos

		is_material_issue = False
		if self.doctype == "Stock Entry" and self.purpose == "Material Issue":
			is_material_issue = True

		for d in self.get("items"):
			if hasattr(d, "serial_no") and hasattr(d, "batch_no") and d.serial_no and d.batch_no:
				serial_nos = frappe.get_all(
					"Serial No",
					fields=["batch_no", "name", "warehouse"],
					filters={"name": ("in", get_serial_nos(d.serial_no))},
				)

				for row in serial_nos:
					if row.warehouse and row.batch_no != d.batch_no:
						frappe.throw(
							_("Row #{0}: Serial No {1} does not belong to Batch {2}").format(
								d.idx, row.name, d.batch_no
							)
						)

			if is_material_issue:
				continue

			if flt(d.qty) > 0.0 and d.get("batch_no") and self.get("posting_date") and self.docstatus < 2:
				expiry_date = frappe.get_cached_value("Batch", d.get("batch_no"), "expiry_date")

				if expiry_date and getdate(expiry_date) < getdate(self.posting_date):
					frappe.throw(
						_("Row #{0}: The batch {1} has already expired.").format(
							d.idx, get_link_to_form("Batch", d.get("batch_no"))
						),
						BatchExpiredError,
					)
   
	def clean_serial_nos(self):
		from erpnext.stock.doctype.serial_no.serial_no import clean_serial_no_string

		for row in self.get("items"):
			if hasattr(row, "serial_no") and row.serial_no:
				# remove extra whitespace and store one serial no on each line
				row.serial_no = clean_serial_no_string(row.serial_no)

		for row in self.get("packed_items") or []:
			if hasattr(row, "serial_no") and row.serial_no:
				# remove extra whitespace and store one serial no on each line
				row.serial_no = clean_serial_no_string(row.serial_no)
   
	def validate_inspection(self):
		"""Checks if quality inspection is set/ is valid for Items that require inspection."""
		inspection_fieldname_map = {
			"Purchase Receipt": "inspection_required_before_purchase",
			"Purchase Invoice": "inspection_required_before_purchase",
			"Sales Invoice": "inspection_required_before_delivery",
			"Delivery Note": "inspection_required_before_delivery",
		}
		inspection_required_fieldname = inspection_fieldname_map.get(self.doctype)

		# return if inspection is not required on document level
		if (
			(not inspection_required_fieldname and self.doctype != "Stock Entry")
			or (self.doctype == "Stock Entry" and not self.inspection_required)
			or (self.doctype in ["Sales Invoice", "Purchase Invoice"] and not self.update_stock)
		):
			return

		for row in self.get("items"):
			qi_required = False
			if inspection_required_fieldname and frappe.db.get_value(
				"Item", row.item_code, inspection_required_fieldname
			):
				qi_required = True
			elif self.doctype == "Stock Entry" and row.t_warehouse:
				qi_required = True  # inward stock needs inspection

			if qi_required:  # validate row only if inspection is required on item level
				self.validate_qi_presence(row)
				if self.docstatus == 1:
					self.validate_qi_submission(row)
					self.validate_qi_rejection(row)
   
	def validate_uom_is_integer(self, uom_field, qty_fields, child_dt=None):
		validate_uom_is_integer(self, uom_field, qty_fields, child_dt)
   
	def validate_customer_provided_item(self):
		for d in self.get("items"):
			# Customer Provided parts will have zero valuation rate
			if frappe.get_cached_value("Item", d.item_code, "is_customer_provided_item"):
				d.allow_zero_valuation_rate = 1
   
	def set_process_loss_qty(self):
		if self.purpose not in ("Manufacture", "Repack"):
			return

		precision = self.precision("process_loss_qty")
		if self.work_order:
			data = frappe.get_all(
				"Work Order Operation",
				filters={"parent": self.work_order},
				fields=["max(process_loss_qty) as process_loss_qty"],
			)

			if data and data[0].process_loss_qty is not None:
				process_loss_qty = data[0].process_loss_qty
				if flt(self.process_loss_qty, precision) != flt(process_loss_qty, precision):
					self.process_loss_qty = flt(process_loss_qty, precision)

					frappe.msgprint(
						_("The Process Loss Qty has reset as per job cards Process Loss Qty"), alert=True
					)

		if not self.process_loss_percentage and not self.process_loss_qty:
			self.process_loss_percentage = frappe.get_cached_value(
				"BOM", self.bom_no, "process_loss_percentage"
			)

		if self.process_loss_percentage and not self.process_loss_qty:
			self.process_loss_qty = flt(
				(flt(self.fg_completed_qty) * flt(self.process_loss_percentage)) / 100
			)
		elif self.process_loss_qty and not self.process_loss_percentage:
			self.process_loss_percentage = flt(
				(flt(self.process_loss_qty) / flt(self.fg_completed_qty)) * 100
			)
   
	def validate_purchase_order(self):
		if self.purpose == "Send to Subcontractor" and self.get("purchase_order"):
			is_old_subcontracting_flow = frappe.db.get_value(
				"Purchase Order", self.purchase_order, "is_old_subcontracting_flow"
			)

			if not is_old_subcontracting_flow:
				frappe.throw(
					_("Please select Subcontracting Order instead of Purchase Order {0}").format(
						self.purchase_order
					)
				)
    
	def validate_subcontracting_order(self):
		if self.get("subcontracting_order") and self.purpose in [
			"Send to Subcontractor",
			"Material Transfer",
		]:
			sco_status = frappe.db.get_value("Subcontracting Order", self.subcontracting_order, "status")

			if sco_status == "Closed":
				frappe.throw(
					_("Cannot create Stock Entry against a closed Subcontracting Order {0}.").format(
						self.subcontracting_order
					)
				)
    
	def mark_finished_and_scrap_items(self):
		if self.purpose != "Repack" and any(
			[d.item_code for d in self.items if (d.is_finished_item and d.t_warehouse)]
		):
			return

		finished_item = self.get_finished_item()

		if not finished_item and self.purpose == "Manufacture":
			# In case of independent Manufacture entry, don't auto set
			# user must decide and set
			return

		for d in self.items:
			if d.t_warehouse and not d.s_warehouse:
				if self.purpose == "Repack" or d.item_code == finished_item:
					d.is_finished_item = 1
				else:
					d.is_scrap_item = 1
			else:
				d.is_finished_item = 0
				d.is_scrap_item = 0
    
	def validate_finished_goods(self):
		"""
		1. Check if FG exists (mfg, repack)
		2. Check if Multiple FG Items are present (mfg)
		3. Check FG Item and Qty against WO if present (mfg)
		"""
		production_item, wo_qty, finished_items = None, 0, []

		wo_details = frappe.db.get_value("Work Order", self.work_order, ["production_item", "qty"])
		if wo_details:
			production_item, wo_qty = wo_details

		for d in self.get("items"):
			if d.is_finished_item:
				if not self.work_order:
					# Independent MFG Entry/ Repack Entry, no WO to match against
					finished_items.append(d.item_code)
					continue

				if d.item_code != production_item:
					frappe.throw(
						_("Finished Item {0} does not match with Work Order {1}").format(
							d.item_code, self.work_order
						)
					)
				elif flt(d.transfer_qty) > flt(self.fg_completed_qty):
					frappe.throw(
						_("Quantity in row {0} ({1}) must be same as manufactured quantity {2}").format(
							d.idx, d.transfer_qty, self.fg_completed_qty
						)
					)

				finished_items.append(d.item_code)

		if not finished_items:
			frappe.throw(
				msg=_("There must be atleast 1 Finished Good in this Stock Entry").format(self.name),
				title=_("Missing Finished Good"),
				exc=FinishedGoodError,
			)

		# if self.purpose == "Manufacture":
		# 	if len(set(finished_items)) > 1:
		# 		frappe.throw(
		# 			msg=_("Multiple items cannot be marked as finished item"),
		# 			title=_("Note"),
		# 			exc=FinishedGoodError,
		# 		)

		# 	allowance_percentage = flt(
		# 		frappe.db.get_single_value(
		# 			"Manufacturing Settings", "overproduction_percentage_for_work_order"
		# 		)
		# 	)
		# 	allowed_qty = wo_qty + ((allowance_percentage / 100) * wo_qty)

		# 	# No work order could mean independent Manufacture entry, if so skip validation
		# 	if self.work_order and self.fg_completed_qty > allowed_qty:
		# 		frappe.throw(
		# 			_("For quantity {0} should not be greater than allowed quantity {1}").format(
		# 				flt(self.fg_completed_qty), allowed_qty
		# 			)
		# 		)
    
	def validate_with_material_request(self):
		for item in self.get("items"):
			material_request = item.material_request or None
			material_request_item = item.material_request_item or None
			if self.purpose == "Material Transfer" and self.outgoing_stock_entry:
				parent_se = frappe.get_value(
					"Proposed Stock Entry Details",
					item.ste_detail,
					["material_request", "material_request_item"],
					as_dict=True,
				)
				if parent_se:
					material_request = parent_se.material_request
					material_request_item = parent_se.material_request_item

			if material_request:
				mreq_item = frappe.db.get_value(
					"Material Request Item",
					{"name": material_request_item, "parent": material_request},
					["item_code", "warehouse", "idx"],
					as_dict=True,
				)
				if mreq_item.item_code != item.item_code:
					frappe.throw(
						_("Item for row {0} does not match Material Request").format(item.idx),
						frappe.MappingMismatchError,
					)
				elif self.purpose == "Material Transfer" and self.add_to_transit:
					continue
 
	def validate_batch(self):
		if self.purpose in [
			"Material Transfer for Manufacture",
			"Manufacture",
			"Repack",
			"Send to Subcontractor",
		]:
			for item in self.get("items"):
				if item.batch_no:
					disabled = frappe.db.get_value("Batch", item.batch_no, "disabled")
					if disabled == 0:
						expiry_date = frappe.db.get_value("Batch", item.batch_no, "expiry_date")
						if expiry_date:
							if getdate(self.posting_date) > getdate(expiry_date):
								frappe.throw(
									_("Batch {0} of Item {1} has expired.").format(
										item.batch_no, item.item_code
									)
								)
					else:
						frappe.throw(
							_("Batch {0} of Item {1} is disabled.").format(item.batch_no, item.item_code)
						)

	def validate_fg_completed_qty(self):
		if self.purpose != "Manufacture":
			return

		fg_qty = defaultdict(float)
		for d in self.items:
			if d.is_finished_item:
				fg_qty[d.item_code] += flt(d.qty)

		if not fg_qty:
			return

		precision = frappe.get_precision("Proposed Stock Entry Details", "qty")
		fg_item = next(iter(fg_qty.keys()))
		fg_item_qty = flt(fg_qty[fg_item], precision)
		fg_completed_qty = flt(self.fg_completed_qty, precision)

		for d in self.items:
			if not fg_qty.get(d.item_code):
				continue

			if (fg_completed_qty - fg_item_qty) > 0:
				self.process_loss_qty = fg_completed_qty - fg_item_qty

			if not self.process_loss_qty:
				continue

			if fg_completed_qty != (flt(fg_item_qty) + flt(self.process_loss_qty, precision)):
				frappe.throw(
					_(
						"Since there is a process loss of {0} units for the finished good {1}, you should reduce the quantity by {0} units for the finished good {1} in the Items Table."
					).format(frappe.bold(self.process_loss_qty), frappe.bold(d.item_code))
				)
    
	def validate_difference_account(self):
		if not cint(erpnext.is_perpetual_inventory_enabled(self.company)):
			return

		for d in self.get("items"):
			if not d.expense_account:
				frappe.throw(
					_(
						"Please enter <b>Difference Account</b> or set default <b>Stock Adjustment Account</b> for company {0}"
					).format(frappe.bold(self.company))
				)

			elif (
				self.is_opening == "Yes"
				and frappe.db.get_value("Account", d.expense_account, "report_type") == "Profit and Loss"
			):
				frappe.throw(
					_(
						"Difference Account must be a Asset/Liability type account, since this Stock Entry is an Opening Entry"
					),
					OpeningEntryAccountError,
				)
    
	def set_job_card_data(self):
		if self.job_card and not self.work_order:
			data = frappe.db.get_value(
				"Job Card", self.job_card, ["for_quantity", "work_order", "bom_no"], as_dict=1
			)
			self.fg_completed_qty = data.for_quantity
			self.work_order = data.work_order
			self.from_bom = 1
			self.bom_no = data.bom_no
   
	def validate_job_card_item(self):
		if not self.job_card:
			return

		if cint(frappe.db.get_single_value("Manufacturing Settings", "job_card_excess_transfer")):
			return

		for row in self.items:
			if row.job_card_item or not row.s_warehouse:
				continue

			msg = f"""Row #{row.idx}: The job card item reference
				is missing. Kindly create the stock entry
				from the job card. If you have added the row manually
				then you won't be able to add job card item reference."""

			frappe.throw(_(msg))
   
	def validate_posting_time(self):
		# set Edit Posting Date and Time to 1 while data import
		if frappe.flags.in_import and self.posting_date:
			self.set_posting_time = 1

		if not getattr(self, "set_posting_time", None):
			now = now_datetime()
			self.posting_date = now.strftime("%Y-%m-%d")
			self.posting_time = now.strftime("%H:%M:%S.%f")
		elif self.posting_time:
			try:
				get_time(self.posting_time)
			except ValueError:
				frappe.throw(_("Invalid Posting Time"))
   
	def set_purpose_for_stock_entry(self):
		if self.stock_entry_type and not self.purpose:
			self.purpose = frappe.get_cached_value("Stock Entry Type", self.stock_entry_type, "purpose")
   
	def validate_duplicate_serial_no(self):
		# In case of repack the source and target serial nos could be same
		for warehouse in ["s_warehouse", "t_warehouse"]:
			serial_nos = []
			for row in self.items:
				if not (row.serial_no and row.get(warehouse)):
					continue

				for sn in get_serial_nos(row.serial_no):
					if sn in serial_nos:
						frappe.throw(
							_("The serial no {0} has added multiple times in the stock entry {1}").format(
								frappe.bold(sn), self.name
							)
						)

					serial_nos.append(sn)
   
	def validate_bom(self):
		for d in self.get("items"):
			if d.bom_no and d.is_finished_item:
				item_code = d.original_item or d.item_code
				validate_bom_no(item_code, d.bom_no)
   
	def validate_work_order(self):
		if self.purpose in (
			"Manufacture",
			"Material Transfer for Manufacture",
			"Material Consumption for Manufacture",
		):
			# check if work order is entered

			if (
				self.purpose == "Manufacture" or self.purpose == "Material Consumption for Manufacture"
			) and self.work_order:
				if not self.fg_completed_qty:
					frappe.throw(_("For Quantity (Manufactured Qty) is mandatory"))
				self.check_if_operations_completed()
				self.check_duplicate_entry_for_work_order()
		elif self.purpose != "Material Transfer":
			self.work_order = None
   
	def validate_warehouse(self):
		"""perform various (sometimes conditional) validations on warehouse"""

		source_mandatory = [
			"Material Issue",
			"Material Transfer",
			"Send to Subcontractor",
			"Material Transfer for Manufacture",
			"Material Consumption for Manufacture",
		]

		target_mandatory = [
			"Material Receipt",
			"Material Transfer",
			"Send to Subcontractor",
			"Material Transfer for Manufacture",
		]

		validate_for_manufacture = any([d.bom_no for d in self.get("items")])

		if self.purpose in source_mandatory and self.purpose not in target_mandatory:
			self.to_warehouse = None
			for d in self.get("items"):
				d.t_warehouse = None
		elif self.purpose in target_mandatory and self.purpose not in source_mandatory:
			self.from_warehouse = None
			for d in self.get("items"):
				d.s_warehouse = None

		for d in self.get("items"):
			if not d.s_warehouse and not d.t_warehouse:
				d.s_warehouse = self.from_warehouse
				d.t_warehouse = self.to_warehouse

			if self.purpose in source_mandatory and not d.s_warehouse:
				if self.from_warehouse:
					d.s_warehouse = self.from_warehouse
				else:
					frappe.throw(_("Source warehouse is mandatory for row {0}").format(d.idx))

			if self.purpose in target_mandatory and not d.t_warehouse:
				if self.to_warehouse:
					d.t_warehouse = self.to_warehouse
				else:
					frappe.throw(_("Target warehouse is mandatory for row {0}").format(d.idx))

			if self.purpose == "Manufacture":
				if validate_for_manufacture:
					if d.is_finished_item or d.is_scrap_item:
						d.s_warehouse = None
						if not d.t_warehouse:
							frappe.throw(_("Target warehouse is mandatory for row {0}").format(d.idx))
					else:
						d.t_warehouse = None
						if not d.s_warehouse:
							frappe.throw(_("Source warehouse is mandatory for row {0}").format(d.idx))

			if cstr(d.s_warehouse) == cstr(d.t_warehouse) and self.purpose not in [
				"Material Transfer for Manufacture",
				"Material Transfer",
			]:
				frappe.throw(_("Source and target warehouse cannot be same for row {0}").format(d.idx))

			if not (d.s_warehouse or d.t_warehouse):
				frappe.throw(_("Atleast one warehouse is mandatory"))
    
	def validate_qty(self):
		manufacture_purpose = ["Manufacture", "Material Consumption for Manufacture"]

		if self.purpose in manufacture_purpose and self.work_order:
			if not frappe.get_value("Work Order", self.work_order, "skip_transfer"):
				item_code = []
				for item in self.items:
					if cstr(item.t_warehouse) == "":
						req_items = frappe.get_all(
							"Work Order Item",
							filters={"parent": self.work_order, "item_code": item.item_code},
							fields=["item_code"],
						)

						transferred_materials = frappe.db.sql(
							"""
									select
										sum(sed.qty) as qty
									from `tabStock Entry` se,`tabProposed Stock Entry Details` sed
									where
										se.name = sed.parent and se.docstatus=1 and
										(se.purpose='Material Transfer for Manufacture' or se.purpose='Manufacture')
										and sed.item_code=%s and se.work_order= %s and ifnull(sed.t_warehouse, '') != ''
								""",
							(item.item_code, self.work_order),
							as_dict=1,
						)

						stock_qty = flt(item.qty)
						trans_qty = flt(transferred_materials[0].qty)
						if req_items:
							if stock_qty > trans_qty:
								item_code.append(item.item_code)
        
	def set_transfer_qty(self):
		for item in self.get("items"):
			if not flt(item.qty):
				frappe.throw(_("Row {0}: Qty is mandatory").format(item.idx), title=_("Zero quantity"))
			if not flt(item.conversion_factor):
				frappe.throw(_("Row {0}: UOM Conversion Factor is mandatory").format(item.idx))
			item.transfer_qty = flt(
				flt(item.qty) * flt(item.conversion_factor), self.precision("transfer_qty", item)
			)
			if not flt(item.transfer_qty):
				frappe.throw(
					_("Row {0}: Qty in Stock UOM can not be zero.").format(item.idx), title=_("Zero quantity")
				)
   
	def validate_item(self):
		stock_items = self.get_stock_items()
		serialized_items = self.get_serialized_items()
		for item in self.get("items"):
			if flt(item.qty) and flt(item.qty) < 0:
				frappe.throw(
					_("Row {0}: The item {1}, quantity must be positive number").format(
						item.idx, frappe.bold(item.item_code)
					)
				)

			if item.item_code not in stock_items:
				frappe.throw(_("{0} is not a stock Item").format(item.item_code))

			item_details = self.get_item_details(
				frappe._dict(
					{
						"item_code": item.item_code,
						"company": self.company,
						"project": self.project,
						"uom": item.uom,
						"s_warehouse": item.s_warehouse,
					}
				),
				for_update=True,
			)

			reset_fields = ("stock_uom", "item_name")
			for field in reset_fields:
				item.set(field, item_details.get(field))

			update_fields = (
				"uom",
				"description",
				"expense_account",
				"cost_center",
				"conversion_factor",
				"barcode",
			)

			for field in update_fields:
				if not item.get(field):
					item.set(field, item_details.get(field))
				if field == "conversion_factor" and item.uom == item_details.get("stock_uom"):
					item.set(field, item_details.get(field))

			if not item.transfer_qty and item.qty:
				item.transfer_qty = flt(
					flt(item.qty) * flt(item.conversion_factor), self.precision("transfer_qty", item)
				)

			if (
				self.purpose in ("Material Transfer", "Material Transfer for Manufacture")
				and not item.serial_no
				and item.item_code in serialized_items
			):
				frappe.throw(
					_("Row #{0}: Please specify Serial No for Item {1}").format(item.idx, item.item_code),
					frappe.MandatoryError,
				)
    
	def get_serialized_items(self):
		serialized_items = []
		item_codes = list(set(d.item_code for d in self.get("items")))
		if item_codes:
			serialized_items = frappe.db.sql_list(
				"""select name from `tabItem`
				where has_serial_no=1 and name in ({})""".format(", ".join(["%s"] * len(item_codes))),
				tuple(item_codes),
			)

		return serialized_items
    
	def get_stock_items(self):
		stock_items = []
		item_codes = list(set(item.item_code for item in self.get("items")))
		if item_codes:
			stock_items = frappe.db.get_values(
				"Item", {"name": ["in", item_codes], "is_stock_item": 1}, pluck="name", cache=True
			)

		return stock_items

	def validate_purpose(self):
		valid_purposes = [
			"Material Issue",
			"Material Receipt",
			"Material Transfer",
			"Material Transfer for Manufacture",
			"Manufacture",
			"Repack",
			"Send to Subcontractor",
			"Material Consumption for Manufacture",
		]

		if self.purpose not in valid_purposes:
			frappe.throw(_("Purpose must be one of {0}").format(comma_or(valid_purposes)))

		if self.job_card and self.purpose not in ["Material Transfer for Manufacture", "Repack"]:
			frappe.throw(
				_(
					"For job card {0}, you can only make the 'Material Transfer for Manufacture' type stock entry"
				).format(self.job_card)
			)
   
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
		# finished_item_qty = sum(d.transfer_qty for d in self.items if d.is_finished_item)

		# items = []
		# # Set basic rate for incoming items
		# for d in self.get("items"):
		# 	if d.s_warehouse or d.set_basic_rate_manually:
		# 		continue

		# 	if d.allow_zero_valuation_rate:
		# 		d.basic_rate = 0.0
		# 		items.append(d.item_code)

		# 	elif d.is_finished_item:
		# 		if self.purpose == "Manufacture":
		# 			d.basic_rate = self.get_basic_rate_for_manufactured_item(
		# 				finished_item_qty, outgoing_items_cost
		# 			)
		# 		elif self.purpose == "Repack":
		# 			d.basic_rate = self.get_basic_rate_for_repacked_items(d.transfer_qty, outgoing_items_cost)

		# 	if not d.basic_rate and not d.allow_zero_valuation_rate:
		# 		d.basic_rate = get_valuation_rate(
		# 			d.item_code,
		# 			d.t_warehouse,
		# 			self.doctype,
		# 			self.name,
		# 			d.allow_zero_valuation_rate,
		# 			currency=erpnext.get_company_currency(self.company),
		# 			company=self.company,
		# 			raise_error_if_no_rate=raise_error_if_no_rate,
		# 			batch_no=d.batch_no,
		# 		)

		# 	# do not round off basic rate to avoid precision loss
		# 	d.basic_rate = flt(d.basic_rate)
		# 	d.basic_amount = flt(flt(d.transfer_qty) * flt(d.basic_rate), d.precision("basic_amount"))

		# if items:
		# 	message = ""

		# 	if len(items) > 1:
		# 		message = (
		# 			"Items rate has been updated to zero as Allow Zero Valuation Rate is checked for the following items: {0}"
		# 		).format(", ".join(frappe.bold(item) for item in items))
		# 	else:
		# 		message = (
		# 			"Item rate has been updated to zero as Allow Zero Valuation Rate is checked for item {0}"
		# 		).format(frappe.bold(items[0]))

		# 	frappe.msgprint(message, alert=True)
	
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
					_(
						"Row {0}: Quantity not available for {4} in warehouse {1} at posting time of the entry ({2} {3})"
					).format(
						d.idx,
						frappe.bold(d.s_warehouse),
						formatdate(self.posting_date),
						format_time(self.posting_time),
						frappe.bold(d.item_code),
					)
					+ "<br><br>"
					+ _("Available quantity is {0}, you need {1}").format(
						frappe.bold(flt(d.actual_qty, d.precision("actual_qty"))), frappe.bold(d.transfer_qty)
					),
					NegativeStockError,
					title=_("Insufficient Stock"),
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

	
	def get_basic_rate_for_manufactured_item(self, finished_item_qty, outgoing_items_cost=0) -> float:
		scrap_items_cost = sum([flt(d.basic_amount) for d in self.get("items") if d.is_scrap_item])

		# Get raw materials cost from BOM if multiple material consumption entries
		if not outgoing_items_cost and frappe.db.get_single_value(
			"Manufacturing Settings", "material_consumption", cache=True
		):
			bom_items = self.get_bom_raw_materials(finished_item_qty)
			outgoing_items_cost = sum([flt(row.qty) * flt(row.rate) for row in bom_items.values()])

		return flt((outgoing_items_cost - scrap_items_cost) / finished_item_qty)

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

def validate_uom_is_integer(doc, uom_field, qty_fields, child_dt=None):
	if isinstance(qty_fields, str):
		qty_fields = [qty_fields]

	distinct_uoms = list(set(d.get(uom_field) for d in doc.get_all_children()))
	integer_uoms = list(
		filter(
			lambda uom: frappe.db.get_value("UOM", uom, "must_be_whole_number", cache=True) or None,
			distinct_uoms,
		)
	)

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


# STOCK ENTRY CUSTOM CODE
# @frappe.whitelist()
# def opcost(self):
# 	if self.purpose == 'Manufacture':
# 		doc=frappe.db.get_all('Process Order',filters={'name':self.process_order})
# 		for d in doc:
# 			doc1=frappe.get_doc('Process Order',d.name)
# 			self.total_additional_costs = doc1.total_operation_cost
# 			for d1 in doc1.get("operation_cost"):
# 				self.append("additional_costs",{
# 						"expense_account":d1.operations,
# 						"amount":d1.cost,
# 						"description":"None",
# 						"base_amount":d1.cost,
# 						}
# 					)
# 			for d2 in doc1.get("finished_products"):
# 				for d3 in self.get("items", filters = {'item_code':d2.item}):
# 					d3.basic_amt_cal = d2.rate
# 					d3.basic_rate = d2.rate
# 					d3.yielding = d2.yeild
# 					d3.batch_no = d2.batch_no
# 					d3.set_basic_rate_manually = "1"
# 					d3.is_finished_item = "1"
# 					d3.basic_amount = d3.qty * d3.basic_rate
# 					d3.t_warehouse = d2.warehouse
# 					pricelst = frappe.get_value("Manufacturing Rate Chart",{"item_code":d3.item_code},"rate")
# 					d3.custom_price_list_rate = pricelst
# 					d3.custom_sale_value = d3.custom_price_list_rate * d3.qty

						
# 			for d4 in doc1.get("scrap"):
# 				for d5 in self.get("items", filters = {'item_code':d4.item}):
# 						d5.basic_rate = d4.rate
# 						d5.basic_amt_cal = d4.rate
# 						d5.yielding = d4.yeild
# 						d3.batch_no = d4.batch_no
# 						d5.set_basic_rate_manually = "1"
# 						d5.is_finished_item = "1"
# 						d5.basic_amount = d5.qty * d5.basic_rate
# 						d5.t_warehouse = d4.warehouse
# 						pricelst = frappe.get_value("Manufacturing Rate Chart",{"item_code":d5.item_code},"rate")
# 						d5.custom_price_list_rate = pricelst
# 						d5.custom_sale_value = d5.custom_price_list_rate * d5.qty

# @frappe.whitelist()
# def valcal(self):
# 	if self.purpose == 'Manufacture':
# 		totsaleval = 0
# 		doc=frappe.db.get_all('Process Order',filters={'name':self.process_order})
# 		rawitemprice = sum(totall.amount  for totall in self.get("items") if totall.t_warehouse == None)
# 		totsaleval = sum(j.custom_sale_value for j in self.get("items") if j.t_warehouse != None)
# 		addcost = sum(addco.amount for addco in self.get("additional_costs"))
# 		for d6 in self.get("items"):
# 			if(d6.s_warehouse == None):
# 				d6.custom_basic_value = (d6.custom_sale_value / totsaleval) * float(rawitemprice)
# 				d6.additional_cost = ((d6.custom_sale_value) / totsaleval) * addcost
# 				d6.basic_rate = d6.custom_basic_value / d6.qty

# @frappe.whitelist()
# def aftersave(self):
# 	if self.purpose == 'Manufacture':
# 		for df in self.get("items"):
# 			if(df.s_warehouse == None):
# 				df.amount = df.basic_rate * df.qty + df.additional_cost
# 	self.save()
				
# @frappe.whitelist()
# def YeildValue(self,doctype):
# 	if self.stock_entry_type == 'Manufacture':
# 		self.total_additional_costs = sum(mk.amount for mk in self.get("additional_costs"))
# 		tarWarQty = 0	
# 		# z = 0		
# 		for m in self.get('items'):
# 			if str(m.t_warehouse) == 'None'or str(m.t_warehouse) == "":
# 				tarWarQty +=(m.qty)
# 		for s in self.get('items'):		
# 			if str(s.s_warehouse) == 'None':
# 				s.is_finished_item = "1"
# 				s.yielding = str((float(s.qty) / float(tarWarQty)) * 100)
# 			z = int(s.basic_rate)
# 			if str(s.yielding) == "None":
# 				s.basic_amt_cal = '0'
# 			else:
# 				pass
# 	else:
# 		pass


# @frappe.whitelist()
# def diffqty(self):
# 	if self.stock_entry_type == 'Manufacture':
# 		tqdif = float(0)
# 		sqdiff = float(0)
# 		for s in self.get('items'):
# 			t_warehouse_str = str(s.t_warehouse)
# 			s_warehouse_str = str(s.s_warehouse)
# 			if t_warehouse_str == "None" or t_warehouse_str == "":
# 				tqdif += s.qty
# 			if s_warehouse_str == "None" or s_warehouse_str == "":
# 				sqdiff += s.qty
# 		self.custom_quantity_difference_ = tqdif - sqdiff
# 		opp =0
# 		for s in self.get('items'):
# 			t_warehouse_str = str(s.t_warehouse)
# 			if t_warehouse_str == "None" or t_warehouse_str == "" :
# 				opp += s.qty
# 		self.custom_in_qty_kg = self.total_additional_costs / float(opp)
