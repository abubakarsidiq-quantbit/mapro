# Copyright (c) 2023, Pradip and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import date

class JobOfferProcess(Document):
	@frappe.whitelist()
	def opcost(self):
		doc=frappe.db.get_list('Process Definition')
		for d in doc:
			doc1=frappe.get_doc('Process Definition',d.name)
			if(self.process_defination==d.name):
				self.definition_material_qty = doc1.materials_qty
				self.materials_amount = doc1.materials_amount
				self.total_operation_cost = doc1.total_operation_cost
				self.materials_qty = doc1.materials_qty
				self.finished_products_qty = doc1.finished_products_qty
				self.finished_products_amount = doc1.finished_products_amount + doc1.total_operation_cost
				for d1 in doc1.get("operation_cost"):
					self.append("operation_cost",{
							"operations":d1.operations,
							"rate":d1.rate,
							"definition_cost":d1.cost,
							}
						)
				for d1 in doc1.get("materials"):
					self.append("materials",{
							"item":d1.item,
							"item_name":d1.item_name,
							"quantity":d1.quantity,
							"rate":d1.rate,
							"yeild":d1.yeild,
							"amount":d1.amount,
							"uom":d1.uom,
							"batch_no":d1.batch_no,"warehouse": d1.warehouse
							}
						)
				for d1 in doc1.get("finished_products"):
					self.append("finished_products",{
							"item":d1.item,
							"item_name":d1.item_name,
							"quantity":d1.quantity,
							"rate":d1.rate,
							"yeild":d1.yeild,
							"amount":d1.amount,
							"uom":d1.uom,
							"batch_no":d1.batch_no,"warehouse": d1.warehouse
							}
						)
				for d1 in doc1.get("scrap"):
					self.append("scrap",{
							"item":d1.item,
							"item_name":d1.item_name,
							"quantity":d1.quantity,
							"rate":d1.rate,
							"yeild":d1.yeild,
							"amount":d1.amount,
							"uom":d1.uom,
							"batch_no":d1.batch_no,
							"warehouse":d1.warehouse
							}
						)

	@frappe.whitelist()
	def qtyupdate(self):
		self.secondTrigger()
		# self.secondTrigger()
    
	@frappe.whitelist()
	def secondTrigger(self):
		temp=''
		
  
		for m in self.get('materials'):
			temp=m.quantity
			if m.quantity > 0:
				m.quantity=(self.quantity * m.yeild) / 100
			m.amount=float(m.quantity)*float(m.rate)
		self.materials_qty = sum(m.quantity for m in self.get("materials"))
		self.materials_amount = sum(m.amount for m in self.get("materials"))
		for toc in self.get('operation_cost'):
			if self.definition_material_qty:
				toc.cost=((float(toc.definition_cost)/float(self.definition_material_qty)) * float(self.quantity))
		self.total_operation_cost = sum(toc.cost for toc in self.get("operation_cost"))
   
		for fp in self.get('finished_products'):
			if fp.quantity >0:
				fp.quantity=str((int(fp.quantity)*int(self.quantity))/int(temp))
				fp.quantity = (fp.yeild / 100) * self.materials_qty
			fp.amount=float(fp.quantity)*float(fp.rate)
			pricelst = frappe.get_all("Manufacturing Rate Chart",{'process_type':self.process_type,'item_code':fp.item,'from_date': ['<',date.today()]},"rate")
			# if len(pricelst)>=2:
			# 	frappe.throw(f"There Are Multiple Rate Chart For {fp.item} Item At Manufacturing Rate Chart.")
			# else:
			if pricelst:
				fp.manufacturing_rate = pricelst[0]['rate']
				fp.sale_value = fp.quantity * fp.manufacturing_rate
			else:
				fp.manufacturing_rate = 0
				fp.sale_value = 0
				fp.basic_value = 0
			if fp.quantity == None:
				fp.quantity = 0
    
		for sc in self.get('scrap'):
			pricelst = frappe.get_value("Manufacturing Rate Chart",{'process_type':self.process_type,"item_code":sc.item},"rate")
			if(pricelst):
				sc.manufacturing_rate = pricelst
			else:
				sc.manufacturing_rate = 0
			sc.sale_value = float(sc.quantity) * float(sc.manufacturing_rate)
			
		self.total_scrap_sale_value = sum(sc.sale_value for sc in self.get("scrap"))
  
		self.total_sale_value = sum(fp.sale_value for fp in self.get("finished_products"))
		for sc in self.get('scrap'):
			if temp:
				sc.quantity=str((int(sc.quantity)*int(self.quantity))/int(temp))
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
			fp.total_cost = fp.basic_value
			if fp.total_cost and fp.quantity:
				fp.valuation_rate = fp.total_cost/fp.quantity
				fp.amount = fp.valuation_rate * fp.quantity
			else:
				fp.valuation_rate = 0
				fp.amount = 0
    
		self.scrap_qty = sum(sc.quantity for sc in self.get("scrap"))
		scrap_amount = 0
		for sc in self.scrap:
			scrap_amount = scrap_amount + sc.amount
		self.scrap_amount = scrap_amount
		self.finished_products_qty = sum(fp.quantity for fp in self.get("finished_products"))
		self.finished_products_amount  = sum(fp.amount for fp in self.get("finished_products"))

		if self.scrap_qty or self.finished_products_qty:
			self.all_finish_qty=self.finished_products_qty+ self.scrap_qty
		else:
			self.all_finish_qty = 0
   
		if self.scrap_amount or self.finished_products_amount:
			self.total_all_amount=self.finished_products_amount + self.scrap_amount
		else:
			self.total_all_amount = 0

		self.diff_qty=float(self.all_finish_qty)-float(self.materials_qty)
		# self.diff_amt=float(self.materials_amount+self.total_operation_cost)-float(self.total_all_amount)
		self.diff_amt=float(self.total_all_amount) - float(self.materials_amount)

	# @frappe.whitelist()
	# def secondTrigger(self):
	# 	temp=''
	# 	tocq=0.0
	# 	tbam=0.0
	# 	sc_qty, sc_amt, sc_sale_amt = 0,0,0
  
	# 	for m in self.get('materials'):
	# 		temp=m.quantity
	# 		if m.quantity > 0:
	# 			m.quantity=(self.quantity * m.yeild) / 100
	# 		tbam=float(m.quantity)*float(m.rate)
	# 		m.amount=tbam
	# 		self.materials_qty = sum(m.quantity for m in self.get("materials"))
	# 		self.materials_amount = sum(m.amount for m in self.get("materials"))
	# 	for toc in self.get('operation_cost'):
	# 		toc.cost=((float(toc.definition_cost)/float(self.definition_material_qty)) * float(self.quantity))
	# 		tocq=float(tocq)+float(toc.cost)
	# 		self.total_operation_cost = sum(toc.cost for toc in self.get("operation_cost"))
   
	# 	for fp in self.get('finished_products'):
	# 		if fp.quantity >0:
	# 			fp.quantity=str((int(fp.quantity)*int(self.quantity))/int(temp))
	# 			fp.quantity = (fp.yeild / 100) * self.materials_qty
	# 		tbam=float(fp.quantity)*float(fp.rate)
	# 		fp.amount=tbam
	# 		pricelst = frappe.get_value("Manufacturing Rate Chart",{'process_type':self.process_type,"item_code":fp.item},"rate")
	# 		fp.manufacturing_rate = pricelst
	# 		if fp.manufacturing_rate == None:
	# 			fp.manufacturing_rate = 0
	# 		if fp.quantity == None:
	# 			fp.quantity = 0
	# 		fp.sale_value = fp.quantity * fp.manufacturing_rate
	# 		self.total_sale_value = sum(fp.sale_value for fp in self.get("finished_products"))
	# 		self.finished_products_qty = sum(fp.quantity for fp in self.get("finished_products"))
	# 		self.finished_products_amount = sum(fp.amount for fp in self.get("finished_products"))
	# 		#Removed From Here Code - 1
	# 		if fp.sale_value >0:
	# 			fp.basic_value = (fp.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
	# 		if fp.basic_value >0:
	# 			fp.rate = fp.basic_value / fp.quantity
	# 		fp.amount = fp.rate * fp.quantity
  
	# 	for sc in self.get('scrap'):
	# 		if self.quantity:	
	# 			sc.quantity=str((int(sc.quantity)*int(self.quantity))/int(temp))
	# 			sc.quantity = (sc.yeild / 100) * self.materials_qty
	# 			tbam=float(sc.quantity)*float(sc.rate)
	# 			sc.amount=tbam
	# 			if sc.sale_value >0:
	# 				sc.basic_value = (sc.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
	# 			if sc.quantity:
	# 				sc.rate = sc.basic_value / sc.quantity
	# 				sc.amount = sc.rate * sc.quantity
	# 			sc_qty += sc.quantity
	# 			sc_amt += sc.amount
	# 			sc_sale_amt += sc.sale_value

	# 	self.all_finish_qty=self.finished_products_qty+self.scrap_qty
	# 	self.total_all_amount=self.finished_products_amount+self.scrap_amount
	# 	self.scrap_qty = sc_qty
	# 	self.scrap_amount = sc_amt
	# 	self.total_scrap_sale_value = sum(sc.sale_value for sc in self.get("scrap"))
	# 	self.total_operation_cost=tocq
	# 	self.diff_qty=float(self.finished_products_qty+ self.scrap_qty)-float(self.materials_qty)
	# 	self.diff_amt=float(self.materials_amount+self.total_operation_cost)-float(self.total_all_amount)

	# 	for ok in self.get('finished_products'):
	# 		if ok.amount >0:
	# 			ok.operation_cost = ( ok.amount / self.total_all_amount ) * self.total_operation_cost
	# 		ok.total_cost = ok.amount + ok.operation_cost
	# 		if ok.total_cost>0 and ok.quantity:
	# 			ok.valuation_rate = ok.total_cost / ok.quantity
	# 	for yes in self.get('scrap'):
	# 		if yes.amount >0:
	# 			yes.operation_cost = ( yes.amount / self.total_all_amount ) * self.total_operation_cost
	# 		yes.total_cost = yes.amount + yes.operation_cost
	# 		if yes.total_cost>0:
	# 			yes.valuation_rate = yes.total_cost / yes.quantity

	@frappe.whitelist()
	def Get_Purchase_Rate(self,item,index):
		ratevar = frappe.get_value("Bin", {"item_code": item, "warehouse": self.src_warehouse, "actual_qty": (">", 0)}, "valuation_rate")
		if(ratevar):
			self.get("materials")[index-1].rate=ratevar


#------------------------------------Removed From Here Code - 1------------------------------------------#
# for sc in self.get('scrap'):
# 	pricelst = frappe.get_value("Manufacturing Rate Chart",{'process_type':self.process_type,"item_code":sc.item},"rate")
# 	if(pricelst):
# 		sc.manufacturing_rate = pricelst
# 	else:
# 		sc.manufacturing_rate = 0
# 	sc.sale_value = float(sc.quantity) * float(sc.manufacturing_rate)
#	self.scrap_qty = sum(sc.quantity for sc in self.get("scrap"))
#	self.scrap_amount = sum(sc.amount for sc in self.get("scrap"))
#	self.total_scrap_sale_value = sum(sc.sale_value for sc in self.get("scrap"))



# temp=0.0
# tbam=0.0

# for m in self.get('materials'):
# 	temp=m.quantity
# 	m.quantity=self.quantity
# 	tbam=float(m.quantity)*float(m.rate)
# 	m.amount=tbam
# 	self.materials_qty = sum(float(m.quantity) for m in self.get("materials"))
# 	self.materials_amount = sum(float(m.amount) for m in self.get("materials"))
# for pqr in self.get('operation_cost'):
# 	self.total_operation_cost = sum(pqr.cost for pqr in self.get("operation_cost"))
# for mnq in self.get('finished_products'):
# 	self.total_sale_value = sum(mnq.sale_value for mnq in self.get("finished_products"))
# 	self.finished_products_qty = sum(mnq.quantity for mnq in self.get("finished_products"))
# 	self.finished_products_amount = sum(mnq.amount for mnq in self.get("finished_products"))
# for sccc in self.get('scrap'):
# 	self.scrap_qty = sum(sccc.quantity for sccc in self.get("scrap"))
# 	self.scrap_amount = sum(sccc.amount for sccc in self.get("scrap"))


# for fp in self.get('finished_products'):
# 	fp.quantity=(float(fp.quantity)*float(self.quantity))/float(temp)
# 	fp.quantity = (fp.yeild / 100) * self.materials_qty
# 	tbam=float(fp.quantity)*float(fp.rate)
# 	fp.amount=tbam
# 	pricelst = frappe.get_value("Manufacturing Rate Chart",{'process_type':self.process_type,"item_code":fp.item},"rate")
# 	fp.manufacturing_rate = pricelst
# 	if fp.manufacturing_rate == None:
# 		fp.manufacturing_rate = 0
# 	if fp.quantity == None:
# 		fp.quantity = 0
# 	fp.sale_value = fp.quantity * fp.manufacturing_rate
# 	for sc in self.get('scrap'):
# 		pricelst = frappe.get_value("Manufacturing Rate Chart",{'process_type':self.process_type,"item_code":sc.item},"rate")
# 		if(pricelst):
# 			sc.manufacturing_rate = pricelst
# 		else:
# 			sc.manufacturing_rate = 0
# 		sc.quantity=(float(sc.quantity)*float(self.quantity))/float(temp)
# 		sc.quantity = (sc.yeild / 100) * self.materials_qty
# 		tbam=float(sc.quantity)*float(sc.rate)
# 		sc.amount=tbam
# 		sc.sale_value = float(sc.quantity) * float(sc.manufacturing_rate)
# 		self.total_scrap_sale_value = sum(sc.sale_value for sc in self.get("scrap"))
# 		if sc.sale_value >0:
# 			sc.basic_value = (sc.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
# 		sc.rate = sc.basic_value / sc.quantity
# 		sc.amount = sc.rate * sc.quantity
# 	for toc in self.get('operation_cost'):
# 		toc.cost=(float(toc.cost)*int(self.quantity))/float(temp)
# 		# self.total_operation_cost = sum(toc.cost for toc in self.get("operation_cost"))
# 		if fp.sale_value >0:
# 			fp.basic_value = (fp.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
# 	fp.rate = fp.basic_value / fp.quantity
# 	fp.amount = fp.rate * fp.quantity
# self.all_finish_qty=self.finished_products_qty+self.scrap_qty
# self.total_all_amount=self.finished_products_amount+self.scrap_amount		
# self.diff_qty=float(self.all_finish_qty)-float(self.materials_qty)
# self.diff_amt=float(self.materials_amount+self.total_operation_cost)-float(self.total_all_amount)

# for ok in self.get('finished_products'):
# 	if ok.amount >0:
# 		ok.operation_cost = ( ok.amount / self.total_all_amount ) * self.total_operation_cost
# 	ok.total_cost = ok.amount + ok.operation_cost
# 	ok.valuation_rate = ok.total_cost / ok.quantity
# for yes in self.get('scrap'):
# 	if yes.amount >0:
# 		yes.operation_cost = ( yes.amount / self.total_all_amount ) * self.total_operation_cost
# 	yes.total_cost = yes.amount + yes.operation_cost
# 	yes.valuation_rate = yes.total_cost / yes.quantity