// Copyright (c) 2023, Pradip and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Process Item", "item", function(frm, cdt, cdn) {
//     var d = locals[cdt][cdn];
//     frm.call	({
// 			method:"Get_Purchase_Rate",
// 			args:{
// 				item:d.item
// 				},				
// 				callback: function(r) {	
// 						frm.refresh_field('itemwise_batch_details');
// 						var prate = r.message[0]["valuation_rate"];
// 						frappe.model.set_value(cdt, cdn, 'rate',prate);
// 				}
// 		});
//     console.log(d);
// });

// frappe.ui.form.on('Process Item', {
// 	item:function(frm) {
// 		// your code here
// 		frm.call({
// 			method:'Get_Purchase_Rate',
// 			doc: frm.doc,
// 		});
// 	}
// })

frappe.ui.form.on('Process Definition', {
	setup: function (frm) {
		frm.set_query("workstation", function () {
			return {
				filters: {"department": frm.doc.department}
			}
		});
	}
});

frappe.ui.form.on('Operation Cost', {
	rate:function(frm, cdt, cdn) {
		var d = locals[cdt][cdn];
		if(frm.doc.process_type == 'Subcontracting'){
			frappe.model.set_value(cdt, cdn, 'cost', (d.rate * frm.doc.materials_qty));
		}
	}
})

frappe.ui.form.on('Process Item', {
	batch_no: function(frm, cdt, cdn){
		var d = locals[cdt][cdn];
		if(d.warehouse && d.item && frm.doc.date){
			frappe.call({
				method: 'mapro.manufacuring_mode.doctype.process_definition.process_definition.get_batch_rate',
				args: {
					doc: frm.doc,
					item: d.item,
					warehouse: d.warehouse,
					batch_no: d.batch_no,
					date: frm.doc.date
				},
				callback: function(r){
					frappe.model.set_value(cdt, cdn, 'rate', r.message);
					frappe.model.set_value(cdt, cdn, 'amount', (r.message * d.quantity));
				}
			});
		}
		// else{
		// 	frappe.throw("Check Item, Warehouse, Date is Set.")
		// }
    },
	quantity: function(frm, cdt, cdn){
		var d = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, 'amount', (d.rate * d.quantity));
	}
})


frappe.ui.form.on('Process Definition', {
	// before_save:function(frm) {
	// 	frm.call({
	// 		method:'qtyupdate',
	// 		doc: frm.doc,
	// 	});
	// },
	setup: function (frm) {
        frm.set_query("operations", "operation_cost", function (doc, cdt, cdn) {
            return {
                filters: [['Account', 'company', '=', frm.doc.company],
						  ['Account', 'account_type', '=', 'Expenses Included In Valuation'],
						  ['Account', 'is_group', '=', 0]]
            };
        });
	}
})