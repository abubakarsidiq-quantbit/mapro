# Copyright (c) 2023, Pradip and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class JobOfferProcess(Document):
	# @frappe.whitelist()
	# def upend_opcost_table(self):
	# 	doc=frappe.db.get_list('Process Definition')
	# 	for d in doc:
	# 		doc1=frappe.get_doc('Process Definition',{'name':self.process_defination},d.name)
	# 		if(self.process_defination==d.name):
	# 			for d1 in doc1.get("operation_cost"):
	# 				self.append("operation_cost",{
	# 						"operations":d1.operations,
	# 						"cost":d1.cost,
	# 						"definition_cost":d1.cost,
	# 						"is_check":'0'
	# 						}
	# 					)
					
	@frappe.whitelist()
	# def get_process_details(self):
	def opcost(self):
		doc=frappe.db.get_list('Process Definition')
		for d in doc:
			doc1=frappe.get_doc('Process Definition',d.name)
			if(self.process_defination==d.name):
				self.definition_material_qty = doc1.materials_qty
				for d1 in doc1.get("operation_cost"):
					self.append("operation_cost",{
							"operations":d1.operations,
							# "cost":d1.cost,
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
							"batch_no":d1.batch_no
							
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
							"batch_no":d1.batch_no
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
							"batch_no":d1.batch_no
							}
						)
				# for d1 in doc1.get("operation_cost"):
				# 	self.append("operation_cost",{
				# 			"operations":d1.operations,
				# 			"cost":d1.cost,
				# 			}
				# 		)
	@frappe.whitelist()
	def qtyupdate(self):
		self.secondTrigger()
		self.secondTrigger()
     
	@frappe.whitelist()
	def secondTrigger(self):
		temp=''
		# mqty=0.0
		# fpq=0.0
		# scq=0.0
		tocq=0.0
		# mam=0.0
		# fpam=0.0
		# scam=0.0
		tbam=0.0
  
		for m in self.get('materials'):
			temp=m.quantity
			if m.quantity > 0:
				m.quantity=(self.quantity * m.yeild) / 100
			tbam=float(m.quantity)*float(m.rate)
			m.amount=tbam
			self.materials_qty = sum(m.quantity for m in self.get("materials"))
			self.materials_amount = sum(m.amount for m in self.get("materials"))
		for toc in self.get('operation_cost'):
			# if(toc.is_check == 0):
				# toc.cost=(float(self.quantity)*float(self.definition_material_qty))
			toc.cost=((float(toc.definition_cost)/float(self.definition_material_qty)) * float(self.quantity))
			# toc.cost= toc.definition_cost + 100
				# toc.is_check  = '1'
			# toc.cost = (toc.cost / self.definition_material_qty ) * self.quantity
			tocq=float(tocq)+float(toc.cost)
			self.total_operation_cost = sum(toc.cost for toc in self.get("operation_cost"))
   
		for fp in self.get('finished_products'):
			if fp.quantity >0:
				fp.quantity=str((int(fp.quantity)*int(self.quantity))/int(temp))
				fp.quantity = (fp.yeild / 100) * self.materials_qty
			tbam=float(fp.quantity)*float(fp.rate)
			fp.amount=tbam
			# fpam=float(fpam)+float(fp.amount)
			# fpq=float(fpq)+float(fp.quantity)
			pricelst = frappe.get_value("Manufacturing Rate Chart",{'process_type':self.process_type,"item_code":fp.item},"rate")
			fp.manufacturing_rate = pricelst
			if fp.manufacturing_rate == None:
				fp.manufacturing_rate = 0
			if fp.quantity == None:
				fp.quantity = 0
			fp.sale_value = fp.quantity * fp.manufacturing_rate
			self.total_sale_value = sum(fp.sale_value for fp in self.get("finished_products"))
			self.finished_products_qty = sum(fp.quantity for fp in self.get("finished_products"))
			self.finished_products_amount = sum(fp.amount for fp in self.get("finished_products"))
			for sc in self.get('scrap'):
				pricelst = frappe.get_value("Manufacturing Rate Chart",{'process_type':self.process_type,"item_code":sc.item},"rate")
				if(pricelst):
					sc.manufacturing_rate = pricelst
				else:
					sc.manufacturing_rate = 0
				sc.sale_value = float(sc.quantity) * float(sc.manufacturing_rate)
				self.scrap_qty = sum(sc.quantity for sc in self.get("scrap"))
				self.scrap_amount = sum(sc.amount for sc in self.get("scrap"))
				self.total_scrap_sale_value = sum(sc.sale_value for sc in self.get("scrap"))
			if fp.sale_value >0:
				fp.basic_value = (fp.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
			# fp.basic_value = (fp.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount + self.total_operation_cost)
			if fp.basic_value >0:
				fp.rate = fp.basic_value / fp.quantity
			fp.amount = fp.rate * fp.quantity
  
		for sc in self.get('scrap'):	
			sc.quantity=str((int(sc.quantity)*int(self.quantity))/int(temp))
			sc.quantity = (sc.yeild / 100) * self.materials_qty
			tbam=float(sc.quantity)*float(sc.rate)
			sc.amount=tbam
			# scam=float(scam)+float(sc.amount)
			# scq=float(scq)+float(sc.quantity)
			# pricelst = frappe.get_value("Manufacturing Rate Chart",{'process_type':self.process_type,"item_code":sc.item},"rate")
			# sc.manufacturing_rate = pricelst
			# sc.sale_value = sc.quantity * sc.manufacturing_rate
			# self.total_scrap_sale_value = sum(sc.sale_value for sc in self.get("scrap"))
			# sc.basic_value = (sc.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount + self.total_operation_cost)
			if sc.sale_value >0:
				sc.basic_value = (sc.sale_value / (self.total_sale_value +self.total_scrap_sale_value)) * (self.materials_amount)
			sc.rate = sc.basic_value / sc.quantity
			sc.amount = sc.rate * sc.quantity

		
		# self.scrap_qty=scq
		# self.scrap_amount=scam

		self.all_finish_qty=self.finished_products_qty+self.scrap_qty
		self.total_all_amount=self.finished_products_amount+self.scrap_amount

		
  
		# for toc in self.get('operation_cost'):
		# 	toc.cost=str((int(toc.cost)*int(self.quantity))/int(temp))
		# 	tocq=float(tocq)+float(toc.cost)
		
		self.total_operation_cost=tocq
		self.diff_qty=float(self.all_finish_qty)-float(self.materials_qty)
		self.diff_amt=float(self.materials_amount+self.total_operation_cost)-float(self.total_all_amount)

		for ok in self.get('finished_products'):
			if ok.amount >0:
				ok.operation_cost = ( ok.amount / self.total_all_amount ) * self.total_operation_cost
			ok.total_cost = ok.amount + ok.operation_cost
			if ok.total_cost>0:
				ok.valuation_rate = ok.total_cost / ok.quantity
		for yes in self.get('scrap'):
			if yes.amount >0:
				yes.operation_cost = ( yes.amount / self.total_all_amount ) * self.total_operation_cost
			yes.total_cost = yes.amount + yes.operation_cost
			if yes.total_cost>0:
				yes.valuation_rate = yes.total_cost / yes.quantity


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

	@frappe.whitelist()
	def Get_Purchase_Rate(self,item,index):
		ratevar = frappe.get_value("Bin", {"item_code": item, "warehouse": self.src_warehouse, "actual_qty": (">", 0)}, "valuation_rate")
		if(ratevar):
			self.get("materials")[index-1].rate=ratevar

