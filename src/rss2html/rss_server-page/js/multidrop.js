import { Multidrop } from '../modules/multidrop/js/multidrop.js'

const DEBUG = true

//const group_names = ["favorites", "others"]
let prev_feed_groups = new Map()


function compareArrays(a, b) {
	return a.length === b.length
		&& a.every((element, index) => element === b[index])
}
function compareObjects(a, b) {
	let aK = Object.keys(a)
	let bK = Object.keys(b)
	return aK.length === bK.length
		&& aK.every((element, index) => a[element] === b[element])
	  && compareArrays(aK, bK)
}

function get_group_names() {
	let items = document.querySelectorAll('.fav_group')
	return Array.from(items, item => item.getAttribute("group_name"))
}

function feeds_of_group(group_name) {
	//let items = document.getElementById(group_name).querySelectorAll('[draggable=true]')
	let items = document.querySelectorAll('.fav_group[group_name="'+group_name+'"] [draggable=true]')
	let feed_ids = []
	items.forEach(function (item) {
		if (!item.classList.contains('drag_empty')){
			feed_ids.push(item.getAttribute("feed_id"))
		}
	})
	//DEBUG && console.log(`feed_ids = ${feed_ids}`)
	return feed_ids
}


// ===========================
//Handlers
function rss_drop_handler(el, permutation, transfererd_elements){
	// Note: Permutation is restricted on silbings of drop element.
	// If multiple drop zones exists this is just a subset of all dragable elements.
	// Use drop_after-Event to process all dragable elements after drag.
	var positions = permutation.map( p => p.index)
	console.log('Permutation is ' + positions)

  // Backup state before permutation applies.
	prev_feed_groups.clear()
	get_group_names().forEach( group_name => {
		var foo = feeds_of_group(group_name)
		prev_feed_groups.set(group_name, foo)
	})

}

function rss_send_new_order(){
  DEBUG && console.log('Send new order to server')

	let feed_groups = new Map()
	get_group_names().forEach( group_name => {
		feed_groups.set(group_name, feeds_of_group(group_name))
	})

	DEBUG && console.log(`Update feed groups '${feed_groups}'.`)
	change_feed_order(feed_groups)

}

function change_feed_order(feed_groups) {

  /*
	// Like <form enctype="multipart/form-data">
	var data = new FormData();
	data.append("form_name", "change_feed_order")
	feed_groups.forEach( (feed_ids, group_name) => {
	data.append("groups", group_name)
	data.append("feed_ids", feed_ids)
	})
	data.append("save", "0")
	*/

	// Like <form enctype="application/x-www-form-urlencoded">
	let groups = Array.from(feed_groups.keys())
	let feed_ids = Array.from(feed_groups.values(), y => y.join(","))
	var data = JSON.stringify({
		form_name : "change_feed_order",
		groups: groups,
		feed_ids : feed_ids,
		save : "0"
	})
	DEBUG && console.log(data) 

	const url = "change_feed_order"
	fetch(url, {
		method : "POST",
		headers: {
			"Content-Type": "application/json",
			// 'Content-Type': 'application/x-www-form-urlencoded'
		},
		body: data,
	}).then(
		response => response.text() // .json(), etc.
	).then(
		html => console.log(html)
	);
}

// ===========================

var mds = []
/* Note: Do not use objects as keys in other objects: 
 * mds = {},
 * list = document.querySelectorAll('.feed_list')
 * mds[list[0]] = ...
 * mds[list[1]] = ...
 * => this will alter the same position!
 */
function init_multidrop(){
  let lists = Array.from(
    document.querySelectorAll('.feed_list'))

  mds.push(new Multidrop(lists,
    {'drop': rss_drop_handler,
     'drop_after': rss_send_new_order,
    },
    {'clear_selection_after_drop': true,
      'select_by_drag': true,
      'select_by_click': false,
      'select_by_dblclick': true,
		})
  )

  console.log(mds)
}

window.addEventListener('DOMContentLoaded', init_multidrop)
