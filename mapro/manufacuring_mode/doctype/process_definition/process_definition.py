# Copyright (c) 2023, Pradip and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from datetime import date
from erpnext.stock.utils import get_combine_datetime
from frappe.query_builder.functions import Sum
from erpnext.stock.stock_ledger import get_valuation_rate

class ProcessDefinition(Document):
	@frappe.whitelist()
	def Get_Purchase_Rate(item):
		query = """select  valuation_rate from `tabBin` where item_code = %(items)s order by creation LIMIT 1"""
		data = frappe.db.sql(query, {"items": item},as_dict=1)
		return data	

	def before_save(self):
		self.qtyupdate()

	@frappe.whitelist()
	def qtyupdate(self):
		mqty, fpq, scq, tocq, mam, fpam, scam = 0,0,0,0,0,0,0
		
		for m in self.get('materials'):
			if float(m.rate)>0:
				mqty=float(mqty)+m.quantity
				m.amount=float(m.quantity)*float(m.rate)
				mam=float(mam)+float(m.amount)
			else:
				frappe.throw("Set Rate of Raw Material Manually or Select Batch To Fetch Average Batch Rate.")
			
			
		self.materials_qty=mqty
		self.materials_amount=mam

		for fp in self.get('finished_products'):
			fp.quantity = (fp.yeild / 100) * self.materials_qty
			fpq=float(fpq)+float(fp.quantity)
			fp.amount=float(fp.quantity)*float(fp.rate)
			fpam=float(fpam)+float(fp.amount)
   
			pricelst = frappe.get_all("Manufacturing Rate Chart",{'process_type':self.process_type,'item_code':fp.item, 'from_date':['<',date.today()]},"rate")
			if len(pricelst)>=2:
				frappe.throw(f"There Are Multiple Rate Chart For {fp.item} Item At Manufacturing Rate Chart.")
			else:
				# frappe.msgprint(str(pricelst))
				if pricelst:
					fp.manufacturing_rate = pricelst[0]['rate']
					fp.sale_value = fp.quantity * fp.manufacturing_rate
				else:
					fp.manufacturing_rate = 0
					fp.sale_value = 0
					fp.basic_value = 0
			if fp.quantity == None:
				fp.quantity = 0

			
		self.finished_products_qty=fpq	
		self.finished_products_amount=fpam
		
		for sc in self.get('scrap'):
			sc.quantity = (sc.yeild / 100) * self.materials_qty
			sc.amount=float(sc.quantity)*float(sc.rate)
   
			pricelst = frappe.get_all("Manufacturing Rate Chart",{'process_type':self.process_type,'item_code':sc.item, 'from_date':['<',date.today()]},"rate")
			if len(pricelst)>=2:
				frappe.throw(f"There Are Multiple Rate Chart For {sc.item} Item At Manufacturing Rate Chart.")
			else:
				# frappe.msgprint(str(pricelst))
				if pricelst:
					sc.manufacturing_rate = pricelst[0]['rate']
					sc.sale_value = sc.quantity * sc.manufacturing_rate
				else:
					sc.manufacturing_rate = 0
					sc.sale_value = 0
					sc.basic_value = 0
			if sc.quantity == None:
				sc.quantity = 0
		
		self.total_scrap_sale_value = sum(sc.sale_value for sc in self.get("scrap"))
  
		self.total_sale_value = sum(fp.sale_value for fp in self.get("finished_products"))
		for sc in self.get('scrap'):
			if self.materials_qty:
				sc.quantity=str((int(sc.quantity)*int(self.materials_qty))/int(self.materials_qty))
			sc.quantity = (sc.yeild / 100) * self.materials_qty
			sc.amount=float(sc.quantity)*float(sc.rate)
			
			if sc.sale_value >0 and (self.total_sale_value +self.total_scrap_sale_value):
				sc.basic_value = (sc.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
			if sc.quantity and sc.basic_value:
				sc.rate = sc.basic_value / sc.quantity
			sc.amount = sc.rate * sc.quantity

		for fp in self.get('finished_products'):
			if fp.sale_value >0 and (self.total_sale_value + self.total_scrap_sale_value):
				fp.basic_value = (fp.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
			else:
				fp.basic_value = 0
		total_basic_value = sum(fp.basic_value for fp in self.get("finished_products"))
		total_scrap_basic_value = sum(fp.basic_value for fp in self.get("finished_products"))
		self.total_operation_cost = sum(toc.cost for toc in self.get("operation_cost"))
		for fp in self.get('finished_products'):
			if total_basic_value:
				fp.operation_cost = (fp.basic_value/total_basic_value) * self.total_operation_cost
			else:
				fp.operation_cost = 0 
			fp.total_cost = fp.operation_cost + fp.basic_value
			if fp.total_cost and fp.quantity:
				fp.valuation_rate = fp.total_cost/fp.quantity
				fp.amount = fp.valuation_rate * fp.quantity
			else:
				fp.valuation_rate = 0
				fp.amount = 0
    
		for fp in self.get('scrap'):
			if total_scrap_basic_value:
				fp.operation_cost = (fp.basic_value/total_scrap_basic_value) * self.total_operation_cost
			else:
				fp.operation_cost = 0 
			fp.total_cost = fp.basic_value
			if fp.total_cost and fp.quantity:
				fp.valuation_rate = fp.total_cost/fp.quantity
				fp.amount = fp.valuation_rate * fp.quantity
			else:
				fp.valuation_rate = 0
				fp.amount = 0
		self.finished_products_amount = sum(fp.amount for fp in self.get("finished_products"))
		self.scrap_qty = sum(sc.quantity for sc in self.get("scrap"))
		self.scrap_amount = sum(sc.amount for sc in self.get("scrap"))
		self.all_finish_qty=self.finished_products_qty+ self.scrap_qty
		self.total_all_amount=self.finished_products_amount+self.scrap_amount
		
		self.total_operation_cost = sum(toc.cost for toc in self.get("operation_cost"))
		self.diff_qty=float(self.all_finish_qty)-float(self.materials_qty)
		self.diff_amt=float(self.materials_amount+self.total_operation_cost)-float(self.total_all_amount)
		if self.materials_qty:
			self.single_qty_cost = self.total_operation_cost / self.materials_qty
   
@frappe.whitelist()
def get_batch_rate(doc, item, warehouse, batch_no, date):
	basic_rate = get_batch_incoming_rate(item, warehouse, batch_no, date)
	return basic_rate or 0

def get_batch_incoming_rate(item_code, warehouse, batch_no, posting_date, posting_time = '23:59:59', creation=None):
	import datetime

	sle = frappe.qb.DocType("Stock Ledger Entry")

	posting_datetime = get_combine_datetime(posting_date, posting_time)
	if not creation:
		posting_datetime = posting_datetime + datetime.timedelta(milliseconds=1)

	timestamp_condition = sle.posting_datetime < posting_datetime
	if creation:
		timestamp_condition |= (sle.posting_datetime == get_combine_datetime(posting_date, posting_time)) & (
			sle.creation < creation
		)

	batch_details = (
		frappe.qb.from_(sle)
		.select(Sum(sle.stock_value_difference).as_("batch_value"), Sum(sle.actual_qty).as_("batch_qty"))
		.where(
			(sle.item_code == item_code)
			& (sle.warehouse == warehouse)
			& (sle.batch_no == batch_no)
			& (sle.is_cancelled == 0)
		)
		.where(timestamp_condition)
	).run(as_dict=True)

	if batch_details and batch_details[0].batch_qty:
		return batch_details[0].batch_value / batch_details[0].batch_qty


@frappe.whitelist()
def qtyupdate(self):
	mqty=0.0
	fpq=0.0
	scq=0.0
	tocq=0.0
	mam=0.0
	fpam=0.0
	scam=0.0
	
	for m in self.get('materials'):
		mqty=float(mqty)+m.quantity
		m.amount=float(m.quantity)*float(m.rate)
		mam=float(mam)+float(m.amount)
		
		
	self.materials_qty=mqty
	self.materials_amount=mam

	for fp in self.get('finished_products'):
		fp.quantity = (fp.yeild / 100) * self.materials_qty
		fpq=float(fpq)+float(fp.quantity)
		fp.amount=float(fp.quantity)*float(fp.rate)
		fpam=float(fpam)+float(fp.amount)

		pricelst = frappe.get_all("Manufacturing Rate Chart",{'process_type':self.process_type,'item_code':fp.item, 'from_date':['<',date.today()]},"rate")
		if len(pricelst)>=2:
			frappe.throw(f"There Are Multiple Rate Chart For {fp.item} Item At Manufacturing Rate Chart.")
		else:
			if pricelst:
				fp.manufacturing_rate = pricelst[0]['rate']
				fp.sale_value = fp.quantity * fp.manufacturing_rate
			else:
				fp.manufacturing_rate = 0
				fp.sale_value = 0
				fp.basic_value = 0
		if fp.quantity == None:
			fp.quantity = 0

		
	self.finished_products_qty=fpq	
	self.finished_products_amount=fpam
	
	for sc in self.get('scrap'):
		sc.quantity = (sc.yeild / 100) * self.materials_qty
		sc.amount=float(sc.quantity)*float(sc.rate)

		pricelst = frappe.get_all("Manufacturing Rate Chart",{'process_type':self.process_type,'item_code':sc.item, 'from_date':['<',date.today()]},"rate")
		if len(pricelst)>=2:
			frappe.throw(f"There Are Multiple Rate Chart For {sc.item} Item At Manufacturing Rate Chart.")
		else:
			if pricelst:
				sc.manufacturing_rate = pricelst[0]['rate']
				sc.sale_value = sc.quantity * sc.manufacturing_rate
			else:
				sc.manufacturing_rate = 0
				sc.sale_value = 0
				sc.basic_value = 0
		if sc.quantity == None:
			sc.quantity = 0
	
	self.total_scrap_sale_value = sum(sc.sale_value for sc in self.get("scrap"))

	self.total_sale_value = sum(fp.sale_value for fp in self.get("finished_products"))
	for sc in self.get('scrap'):
		if self.materials_qty:
			sc.quantity=str((int(sc.quantity)*int(self.materials_qty))/int(self.materials_qty))
		sc.quantity = (sc.yeild / 100) * self.materials_qty
		sc.amount=float(sc.quantity)*float(sc.rate)
		
		if sc.sale_value >0 and (self.total_sale_value +self.total_scrap_sale_value):
			sc.basic_value = (sc.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
		if sc.quantity:
			sc.rate = sc.basic_value / sc.quantity
		sc.amount = sc.rate * sc.quantity

	for fp in self.get('finished_products'):
		if fp.sale_value >0 and (self.total_sale_value + self.total_scrap_sale_value):
			fp.basic_value = (fp.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
		else:
			fp.basic_value = 0
	total_basic_value = sum(fp.basic_value for fp in self.get("finished_products"))
	total_scrap_basic_value = sum(fp.basic_value for fp in self.get("finished_products"))
	for fp in self.get('finished_products'):
		if total_basic_value:
			fp.operation_cost = (fp.basic_value/total_basic_value) * self.total_operation_cost
		else:
			fp.operation_cost = 0 
		fp.total_cost = fp.operation_cost + fp.basic_value
		if fp.total_cost and fp.quantity:
			fp.valuation_rate = fp.total_cost/fp.quantity
			fp.amount = fp.valuation_rate * fp.quantity
		else:
			fp.valuation_rate = 0
			fp.amount = 0

	for fp in self.get('scrap'):
		if total_scrap_basic_value:
			fp.operation_cost = (fp.basic_value/total_scrap_basic_value) * self.total_operation_cost
		else:
			fp.operation_cost = 0 
		fp.total_cost = fp.operation_cost + fp.basic_value
		if fp.total_cost and fp.quantity:
			fp.valuation_rate = fp.total_cost/fp.quantity
			# fp.amount = fp.valuation_rate * fp.quantity
		else:
			fp.valuation_rate = 0
			fp.amount = 0
			
	self.scrap_qty = sum(sc.quantity for sc in self.get("scrap"))
	self.scrap_amount = sum(sc.amount for sc in self.get("scrap"))
	self.all_finish_qty=self.finished_products_qty+self.scrap_qty
	self.total_all_amount=self.finished_products_amount+self.scrap_amount
	self.materials_amount = sum(m.amount for m in self.get("materials"))
	self.total_operation_cost = sum(toc.cost for toc in self.get("operation_cost"))
	self.diff_qty=float(self.all_finish_qty)-float(self.materials_qty)
	self.diff_amt=float(self.materials_amount+self.total_operation_cost)-float(self.total_all_amount)
	if self.materials_qty:
		self.single_qty_cost = self.total_operation_cost / self.materials_qty
  
  
  
  
# @frappe.whitelist()
# def get_warehouse_rate(doc, item, warehouse, date):
# 	basic_rate = 0
# 	return basic_rate or 0

# @frappe.whitelist()
# def get_incoming_rate(args, raise_error_if_no_rate=True):
# 	"""Get Incoming Rate based on valuation method"""
# 	from erpnext.stock.stock_ledger import (
# 		get_batch_incoming_rate,
# 		get_previous_sle,
# 		get_valuation_rate,
# 	)

# 	if isinstance(args, str):
# 		args = json.loads(args)

# 	voucher_no = args.get("voucher_no") or args.get("name")

# 	in_rate = None
# 	if (args.get("serial_no") or "").strip():
# 		in_rate = get_avg_purchase_rate(args.get("serial_no"))
# 	elif args.get("batch_no") and frappe.db.get_value(
# 		"Batch", args.get("batch_no"), "use_batchwise_valuation", cache=True
# 	):
# 		in_rate = get_batch_incoming_rate(
# 			item_code=args.get("item_code"),
# 			warehouse=args.get("warehouse"),
# 			batch_no=args.get("batch_no"),
# 			posting_date=args.get("posting_date"),
# 			posting_time=args.get("posting_time"),
# 		)
# 	else:
# 		valuation_method = get_valuation_method(args.get("item_code"))
# 		previous_sle = get_previous_sle(args)
# 		if valuation_method in ("FIFO", "LIFO"):
# 			if previous_sle:
# 				previous_stock_queue = json.loads(previous_sle.get("stock_queue", "[]") or "[]")
# 				in_rate = (
# 					_get_fifo_lifo_rate(previous_stock_queue, args.get("qty") or 0, valuation_method)
# 					if previous_stock_queue
# 					else 0
# 				)
# 		elif valuation_method == "Moving Average":
# 			in_rate = previous_sle.get("valuation_rate") or 0

# 	if in_rate is None:
# 		in_rate = get_valuation_rate(
# 			args.get("item_code"),
# 			args.get("warehouse"),
# 			args.get("voucher_type"),
# 			voucher_no,
# 			args.get("allow_zero_valuation"),
# 			currency=erpnext.get_company_currency(args.get("company")),
# 			company=args.get("company"),
# 			raise_error_if_no_rate=raise_error_if_no_rate,
# 			batch_no=args.get("batch_no"),
# 		)

# 	return flt(in_rate)

# def get_args_for_incoming_rate(self, item):
# 		return frappe._dict(
# 			{
# 				"item_code": item.item_code,
# 				"warehouse": item.s_warehouse or item.t_warehouse,
# 				"posting_date": self.posting_date,
# 				"posting_time": self.posting_time,
# 				"qty": item.s_warehouse and -1 * flt(item.transfer_qty) or flt(item.transfer_qty),
# 				"serial_no": item.serial_no,
# 				"batch_no": item.batch_no,
# 				"voucher_type": self.doctype,
# 				"voucher_no": self.name,
# 				"company": self.company,
# 				"allow_zero_valuation": item.allow_zero_valuation_rate,
# 			}
# 		)

# @frappe.whitelist()
# def qtyupdate(self):
# 	mqty=0.0
# 	fpq=0.0
# 	scq=0.0
# 	tocq=0.0
# 	mam=0.0
# 	fpam=0.0
# 	scam=0.0
# 	tbam=0.0
	
# 	for m in self.get('materials'):
# 		mqty=float(mqty)+m.quantity
# 		tbam=float(m.quantity)*float(m.rate)
# 		m.amount=tbam
# 		mam=float(mam)+float(m.amount)
		
		
# 	self.materials_qty=mqty
# 	self.materials_amount=mam

# 	for fp in self.get('finished_products'):
# 		fp.quantity = (fp.yeild / 100) * self.materials_qty
# 		fpq=float(fpq)+float(fp.quantity)
# 		tbam=float(fp.quantity)*float(fp.rate)
# 		fp.amount=tbam
# 		fpam=float(fpam)+float(fp.amount)
		
# 	self.finished_products_qty=fpq	
# 	self.finished_products_amount=fpam
	
# 	for sc in self.get('scrap'):
# 		sc.quantity = (sc.yeild / 100) * self.materials_qty
# 		scq=float(scq)+float(sc.quantity)
# 		tbam=float(sc.quantity)*float(sc.rate)
# 		sc.amount=tbam
# 		scam=float(scam)+float(sc.amount)
		
# 	self.scrap_qty=scq
# 	self.scrap_amount=scam

# 	self.all_finish_qty=self.finished_products_qty+self.scrap_qty
# 	self.total_all_amount=self.finished_products_amount+self.scrap_amount
	
# 	for toc in self.get('operation_cost'):
# 		tocq=float(tocq)+float(toc.cost)
		
# 	self.total_operation_cost=tocq
# 	self.diff_qty=float(self.all_finish_qty)-float(self.materials_qty)
# 	self.diff_amt=float(self.materials_amount+self.total_operation_cost)-float(self.total_all_amount)
# 	if self.materials_qty:
# 		self.single_qty_cost = self.total_operation_cost / self.materials_qty