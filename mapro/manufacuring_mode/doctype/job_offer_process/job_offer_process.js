// Copyright (c) 2023, Pradip and contributors
// For license information, please see license.txt

frappe.ui.form.on('Job Offer Process', {
	process_defination:function(frm){
		frm.clear_table("additional_costs")
		frm.refresh_field("additional_costs")
		frm.clear_table("materials")
		frm.refresh_field('materials')
        frm.clear_table("operation_cost")
		frm.refresh_field('operation_cost')
        frm.clear_table("finished_products")
		frm.refresh_field('finished_products')
        frm.clear_table("scrap")
		frm.refresh_field('scrap')
		frm.call	({
			method:"opcost",
			doc:frm.doc,
		})
	}
});

frappe.ui.form.on('Job Offer Process', {
	update_qty: function(frm) {
		frm.call({
			method:'qtyupdate',
			doc: frm.doc,
		});
	}
  });
  
frappe.ui.form.on('Job Offer Process', {
	cost(frm) {
		// your code here
		frm.call({
			method:'qtyupdate',
			doc: frm.doc,
		});
	}
})
frappe.ui.form.on('Job Offer Process', {
	rate(frm) {
		// your code here
		frm.call({
			method:'qtyupdate',
			doc: frm.doc,
		});
	}
})
frappe.ui.form.on('Process Item', {
	quantity(frm) {
		// your code here
		frm.call({
			method:'qtyupdate',
			doc: frm.doc,
		});
	}
})
frappe.ui.form.on('Process Item', {
	yeild(frm) {
		// your code here
		frm.call({
			method:'qtyupdate',
			doc: frm.doc,
		});
	}
})
frappe.ui.form.on('Process Item', {
	rate(frm) {
		// your code here
		frm.call({
			method:'qtyupdate',
			doc: frm.doc,
		});
	}
})
frappe.ui.form.on('Operation Cost', {
	cost:function(frm) {
		// your code here
		frm.call({
			method:'qtyupdate',
			doc: frm.doc,
		});
	}
})

