# Copyright (c) 2023, Pradip and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class JobOfferProcess(Document):
	@frappe.whitelist()
	# def get_process_details(self):
	def opcost(self):
		doc=frappe.db.get_list('Process Definition')
		for d in doc:
			doc1=frappe.get_doc('Process Definition',d.name)
			if(self.process_defination==d.name):
				for d1 in doc1.get("materials"):
					self.append("materials",{
							"item":d1.item,
							"item_name":d1.item_name,
							"quantity":d1.quantity,
							"rate":d1.rate,
							"yeild":d1.yeild,
							"amount":d1.amount,
							"uom":d1.uom
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
							"uom":d1.uom
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
							"uom":d1.uom
							}
						)
				for d1 in doc1.get("operation_cost"):
					self.append("operation_cost",{
							"operations":d1.operations,
							"cost":d1.cost,
							}
						)
     
	@frappe.whitelist()
	def qtyupdate(self):
		temp=''
		mqty=0.0
		fpq=0.0
		scq=0.0
		tocq=0.0
		mam=0.0
		fpam=0.0
		scam=0.0
		tbam=0.0
  
		for m in self.get('materials'):
			temp=m.quantity
			m.quantity=self.quantity
			mqty=float(mqty)+float(m.quantity)
			tbam=float(m.quantity)*float(m.rate)
			m.amount=tbam
			mam=float(mam)+float(m.amount)
			
		self.materials_qty=mqty
		self.materials_amount=mam
   
		for fp in self.get('finished_products'):
			fp.quantity=str((int(fp.quantity)*int(self.quantity))/int(temp))
			fp.quantity = (fp.yeild / 100) * self.materials_qty
			tbam=float(fp.quantity)*float(fp.rate)
			fp.amount=tbam
			fpam=float(fpam)+float(fp.amount)
			fpq=float(fpq)+float(fp.quantity)
		
		self.finished_products_qty=fpq	
		self.finished_products_amount=fpam
  
		for sc in self.get('scrap'):	
			sc.quantity=str((int(sc.quantity)*int(self.quantity))/int(temp))
			sc.quantity = (sc.yeild / 100) * self.materials_qty
			tbam=float(sc.quantity)*float(sc.rate)
			sc.amount=tbam
			scam=float(scam)+float(sc.amount)
			scq=float(scq)+float(sc.quantity)
		
		self.scrap_qty=scq
		self.scrap_amount=scam

		self.all_finish_qty=self.finished_products_qty+self.scrap_qty
		self.total_all_amount=self.finished_products_amount+self.scrap_amount
  
  
		for toc in self.get('operation_cost'):
			toc.cost=str((int(toc.cost)*int(self.quantity))/int(temp))
			tocq=float(tocq)+float(toc.cost)
		
		self.total_operation_cost=tocq
		self.diff_qty=float(self.all_finish_qty)-float(self.materials_qty)
		self.diff_amt=float(self.materials_amount+self.total_operation_cost)-float(self.total_all_amount)
