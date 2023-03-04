/* Assume a set of draggable elements in a box, e.g.
 * Some <li>-Elements in a <ul> with display:flex.
 *
 * This functions allowing selection of multiple elements
 * and shifting them around in the box.
 *
 * TODO: Firing event after.
 * TODO: Decoration stuff during drop phase.
 * TODO: Touch-Events
 */

const DEBUG_DROP = true

class Multidrop {

  options = {
    // Select first entry with 'dragstart', too.
    'select_by_drag': false,
    'select_by_click': true,
    'select_by_dblclick': false,
    'dummy_entry_in_empty_lists': false,
    'clear_selection_after_drop': false,
    'selected_css_class': 'drag_selected',     // source positions
    'over_css_class':  'drag_target',          // target positions
    'drag_started_class': 'drag_started',
    'expand_css_class': 'drag_target_expand',  // indicate adding children
    // Note that both sets, selected and over, can overlap
  }

  events = {
    'decorate': default_decorate,      // drag start
    'undecorate': default_undecorate,  // drag end
    'drop': default_drop_handler,
    'select': default_select_handler,     // select start
    'unselect': default_unselect_handler, // select end
    //'drag_after': default_drag_after_handler,
    'drop_after': default_drop_after_handler,
  }

  #selected_elements = []
  #dragStartElement = null
  #drag_element_of_last_mark = null
  #marked_targets = null
  #handler = {}  // .bind(this) wrapped methods
  #event_registered = {}

  constructor(boxes, events, options) {
    this.boxes = boxes

    this.events = Object.assign({}, this.events, events)
    this.options = Object.assign({}, this.options, options)

    if (this.options.select_by_click) {
      this.register_click_events()
    } else if (this.options.select_by_dblclick) {
      this.register_dblclick_events()
    }
    if (this.options.select_by_drag){
      this.register_drop_events()
    }


    // Search for dummy entries for empty lists
    let indifferent_boxes = null
    this.boxes.forEach((box) => {
      let indifferent_boxes2 = (box.querySelector('.drag_empty') !== null)
      if (indifferent_boxes === null){
      }else if (indifferent_boxes !== indifferent_boxes2){
        console.log("Multidrop error: Not all boxes containing dummy entry for empty list.")
        indifferent_boxes2 = true
      }
      indifferent_boxes = indifferent_boxes2
    })
    this.options.dummy_entry_in_empty_lists = indifferent_boxes
    DEBUG_DROP && console.log(`Use drop dummy entries: ${this.options.dummy_entry_in_empty_lists}`)

    this.check_for_empty_list()
  }

  deconstructor(){
    this.markDragTargetPositions(null, [], [])
    this.clear_elements()
    this.unregister_drop_events()
    this.unregister_click_events()
    this.unregister_dblclick_events()
  }

  get elements() {
    return Array.from(this.#selected_elements)
  }

  add_element(el) {
    if (!(this.#selected_elements.includes(el))) {
      this.#selected_elements.push(el)
      return true
    }
    return false
  }

  remove_element(el) {
    const idx = this.#selected_elements.indexOf(el)
    //console.log("Idx: "+idx)
    if (idx > -1){
      this.#selected_elements.splice(idx,1)
      return true
    }
    return false
  }

  clear_elements() {
    if (this.#selected_elements) {
      this.#selected_elements.splice(0, this.#selected_elements.length)
    }
  }

  markDragTargetPositions(el, targets, selected_elements_in_other_boxes) {
    if (this.#marked_targets){
      this.unmarkDragTargetPositions(this.#drag_element_of_last_mark)
    }

    //console.log("Mark")
    /* Mark affected elements */
    // TODO: Fire eventhandlers here but not set directly?!
    targets.forEach((el) => {
      el.classList.add(this.options.over_css_class)
    }, this)

    if ((selected_elements_in_other_boxes.length > 0) && (targets.length > 0)){
      console.log("Marking")
      targets[targets.length-1].classList.add(this.options.expand_css_class)  
    }

    this.#drag_element_of_last_mark = el
    this.#marked_targets = targets
  }

  unmarkDragTargetPositions(el) {
    if (!(el == this.#drag_element_of_last_mark)
      /* A new mark already overrided values. No need to unmark this again. */
      || !this.#marked_targets) {
      return;
    }

    //console.log("Unmark")
    // TODO: Fire eventhandlers here but not set directly
    this.#marked_targets.forEach((el) => {
      el.classList.remove(this.options.over_css_class)
      el.classList.remove(this.options.expand_css_class)  
    }, this)

    this.#drag_element_of_last_mark = null
    this.#marked_targets = null
  }


  handleDragStart(evt) {
    DEBUG_DROP && console.log("drag start")

    let el = evt.target
    this.#dragStartElement = el

    if (el?.classList.contains('drag_empty')){
      evt.preventDefault()
      return false
    }

    let selected_in_box = this.selected_elements_in_box(this.box(el))

    //evt.multidrop = this
    //evt.selected = this.elements // array-copy, for decorate-call
    //evt.selected = selected_in_box

    if (this.options.select_by_drag){
      // if dragging not require previous selection by click
      // add at least this element to selection.
      if (this.add_element(el)){
        selected_in_box.push(el)
        //evt.selected = this.elements // array-copy
        //this.events.select?.(evt)
				this.events.select?.(evt.currentTarget, this)
      }
    }
    this.events.decorate?.(evt.currentTarget, this)

    evt.dataTransfer.effectAllowed = "move";
    //evt.dataTransfer.setData("selection", Array(items_selected)) // => string
    //evt.dataTransfer.setData("application/x-moz-node", evt.target)
    evt.dataTransfer.setData("text/plain", evt.target.innerText)
  }

  /* Fired after drop ?! */
  handleDragEnd(evt) {
    DEBUG_DROP && console.log("drag end")

    let el = evt.target
    //evt.multidrop = this
    //evt.selected = this.elements // array-copy

    // Reset drop positions
    this.markDragTargetPositions(null, [], [])

    // Undecorate dragged elements
    this.events.undecorate?.(evt.currentTarget, this)

    if (!this.options.clear_selection_after_drop
      //|| el == this.#dragStartElement)
      && evt.dropEffect != 'none')
    {
      // Preserve current selection
			DEBUG_DROP && console.log("Preserve selection")
      return
    }

    // Clear selection of dragged elements
    if (this.options.clear_selection_after_drop){
      //let evt2 = new Event('click')
      //evt2.selected = evt.selected
      this.elements.forEach((el) => {
        //el.dispatchEvent(evt2) // won't fire if option 'select_by_click' is false

				//evt2.currentTarget = el
        this.events.unselect?.(el, this)
      })
      this.clear_elements()
    }

    //this.events.drag_after?.()
  }

  handleDragOver(evt) {
    evt.preventDefault();
    return false;
  }

  /* Visual feedback of drop area */
  handleDragEnter(evt) {
    DEBUG_DROP && console.log("drag enter")

    evt.dataTransfer.dropEffect = "move";
    //evt.multidrop = this

    /* Evaluate affected elements of potential drop on this position.*/
    const box = this.box(evt.currentTarget)
    const M = box.children.length
    let i = this.childIndex(evt.currentTarget)

    let selected_in_box = this.selected_elements_in_box(box)
    let selected_elements_in_other_boxes = this.selected_elements_in_other_boxes(box)

    // Move forward if not enough positions after current element.
    const shift = Math.min(0, M - (i + selected_in_box.length))
    const first = i + shift
    DEBUG_DROP && console.log(`I: ${i} First: ${first}`)

    /* Collect affected elements. Needed to undo making later. */
    const at_least_one_entry = ((selected_elements_in_other_boxes.length>0) && (selected_in_box.length == 0))?1:0

    this.markDragTargetPositions(
      evt.target,
			this.find_draggable_children(box,
				first,
        first + selected_in_box.length + at_least_one_entry
      ),
      selected_elements_in_other_boxes
    )
  }

  /* Note that dragleave event will be called AFTER dragenter 
   * of next element, if the cursor was moved onto another dragable
   * element.
   * Thus, unmarkDragTargetPositions() needs to be called in
   * handleDragEnter to keep the correct order.
   * Nevertheless, if no dragenter event had occoured, we need
   * to unmark elements here.
   * */
  handleDragLeave(evt) {
    DEBUG_DROP && console.log("drag leave")
    this.unmarkDragTargetPositions(evt.target)
    return;
  }

  /* To process the actual drop, add an event listener for the drop event. In the drop handler, you'll need to prevent the browser's default behavior for drops, which is typically some sort of annoying redirect. You can prevent the event from bubbling up the DOM by calling evt.stopPropagation(). */
  handleDrop(evt) {
    DEBUG_DROP && console.log("drag drop")
    evt.stopPropagation(); // stops the browser from redirecting.

    //let s = evt.dataTransfer.getData("selection")
    //console.log(evt.dataTransfer.getData("text/plain"))

    let dragTarget = evt.currentTarget
    DEBUG_DROP && console.log("dragTarget index: " + this.childIndex(dragTarget))

    /* Evaluate element permutation for this drag&drop operation */
    const box = this.box(dragTarget)
    const M = box.children.length
    let i = this.childIndex(dragTarget)

    // Collect children of box which containing the selected
    // elements.
    let selected_children = this.selected_elements_in_box(box)

    // Move forward if not enough positions after current element.
    const selection_len =  selected_children.length
    const shift = Math.min(0, M - (i + selection_len))
    const first = i + shift
    //console.log(`i: ${i} first: ${first} shift: ${shift} #sel: ${selection_len}`)
    
    let permutation = Array(M)
    let posA = 0       //      |AA…AA|     
    let posB = first   // BB…BB|     |BB…BB
    for(let j=0; j<M; j+=1){
      if (posA==first){
        posA = first + selection_len
      }

      if (selected_children.includes(box.children[j])) {
        //console.log(`B ${posB} => ${j}`)
        permutation[posB] = {index: j, el: box.children[j]}
        ++posB
      }else{
        //console.log(`A ${posA} => ${j}`)
        permutation[posA] = {index:j, el: box.children[j]}
        ++posA
      }
    }

    //evt.multidrop = this
    //DEBUG_DROP && console.log(permutation.toString())
    //evt.permutation = permutation

    //evt.transfererd_elements = this.selected_elements_in_other_boxes(box)
    let transfererd_elements = this.selected_elements_in_other_boxes(box)

    //Propagate change (before permutation begins.)
    this.events.drop?.(evt.currentTarget, permutation, transfererd_elements)

    /* Too early here, use dragend-Event! 
    // Reset drop positions
    this.unmarkDragTargetPositions(this.#drag_element_of_last_mark)

    // Reset selection
    this.clear_elements()
    */

    // Re-order elements
    this.permute_elements(box, permutation)

    // Add selected element from other boxes
    this.move_extern(box, first+selection_len, transfererd_elements)

    this.check_for_empty_list()

    // Preserve selection of elements if target == source
    if (dragTarget != this.#dragStartElement){
      this.#dragStartElement = null
    }

    //Propagate change (after permutation ends.)
    this.events.drop_after?.() 

    return false;
  }

	/* Find first n-th elements with draggable property.
	 *
	 * Assuming that tw
	 */
	find_draggable_children(box, from, to) {
		let items = box.querySelectorAll('[draggable=true]');
		return Array.from(items).slice(from,to)
	}

  /* Re-arange box.children elements by permutation
   *
   * box.children[i] := box.children[permutation[i]]
   */
  permute_elements(box, permutation){
    let old_order = Array.from(box.children)
    for( let i=0; i<permutation.length; ++i){
      box.appendChild(old_order[permutation[i].index])
    }
  }

  // Add selected elements from other boxes after last selected children
  move_extern(box, position, elements){
    if (position == box.children.length - 1){
      elements.forEach((el) => {
        box.appendChild(el)
      })
    }else{
    let after = box.children[position+1-1]
      elements.forEach((el) => {
        box.insertBefore(el, after)
      })
    }
  }


  handleClick(evt){
    evt.preventDefault()
    let el = evt.currentTarget  // evt.target could be inner element
    //const box = evt.target.parentElement
    const old_num = this.#selected_elements.length

    //evt.multidrop = this

    if (this.#selected_elements.includes(el)) {
      //evt.selected = this.elements // array-copy
      this.events.unselect?.(evt.currentTarget, this)

      this.remove_element(el)
    }else{
      this.add_element(el)

      //evt.selected = this.elements // array-copy
      //this.events.select?.(evt)
			this.events.select?.(evt.currentTarget, this)
    }

    const new_num = this.#selected_elements.length

    if (!this.options.select_by_drag){
      if (new_num && !old_num){
        this.register_drop_events()
      }else if(old_num && !new_num){
        this.unregister_drop_events()
      }
    }
  }

  register_click_events(){
    if (this.#event_registered['click']) return;

    DEBUG_DROP && console.log("Register click events")

    this.#handler['click'] = this.handleClick.bind(this)

    this.boxes.forEach((box) => {
      let items = box.querySelectorAll('[draggable=true]');
      items.forEach(function (item) {
        if (!item.classList.contains('drag_empty')){ /* filter dummy elements out*/
          item.addEventListener('click', this.#handler['click'],
            {capture:true});
        }
      }, this);
    })

    this.#event_registered['click'] = true
  }

  unregister_click_events(){
    if (!this.#event_registered['click']) return;

    DEBUG_DROP && console.log("Unregister click events")

    this.boxes.forEach((box) => {
      let items = box.querySelectorAll('[draggable=true]');
      items.forEach(function (item) {
        item.removeEventListener('click', this.#handler['click']);
      }, this);
    })

    this.#event_registered['click'] = false
  }

  register_dblclick_events(){
    if (this.#event_registered['dblclick']) return;

    DEBUG_DROP && console.log("Register dblclick events")

    this.#handler['dblclick'] = this.handleClick.bind(this)

    this.boxes.forEach((box) => {
      let items = box.querySelectorAll('[draggable=true]');
      items.forEach(function (item) {
        if (!item.classList.contains('drag_empty')){ /* filter dummy elements out*/
          item.addEventListener('dblclick', this.#handler['dblclick'],
            {capture:true});
        }
      }, this);
    })

    this.#event_registered['dblclick'] = true
  }

  unregister_dblclick_events(){
    if (!this.#event_registered['dblclick']) return;

    DEBUG_DROP && console.log("Unregister dblclick events")

    this.boxes.forEach((box) => {
      let items = box.querySelectorAll('[draggable=true]');
      items.forEach(function (item) {
        item.removeEventListener('dblclick', this.#handler['dblclick']);
      }, this);
    })

    this.#event_registered['dblclick'] = false
  }

  register_drop_events(){
    if (this.#event_registered['drop']) return;

    DEBUG_DROP && console.log("Register Multidrop events")

    this.#handler['dragstart'] = this.handleDragStart.bind(this)
    this.#handler['dragend'] = this.handleDragEnd.bind(this)
    this.#handler['dragover'] = this.handleDragOver.bind(this)
    this.#handler['dragenter'] = this.handleDragEnter.bind(this)
    this.#handler['dragleave'] = this.handleDragLeave.bind(this)
    this.#handler['drop'] = this.handleDrop.bind(this)

    this.boxes.forEach((box) => {
      let items = box.querySelectorAll('[draggable=true]');
      items.forEach(function (item) {
        ['dragstart', 'dragend', 'dragover',
          'dragenter', 'dragleave', 'drop'].forEach(
            function(ename){
              item.addEventListener(ename, this.#handler[ename]);
            }, this)
      }, this);
    })

    this.#event_registered['drop'] = true
  }

  unregister_drop_events(){
    if (!this.#event_registered['drop']) return;

    DEBUG_DROP && console.log("Unregister Multidrop events")

    this.boxes.forEach((box) => {
      let items = box.querySelectorAll('[draggable=true]');

      items.forEach(function (item) {
        ['dragstart', 'dragend', 'dragover',
          'dragenter', 'dragleave', 'drop'].forEach(
            function(ename){
              item.removeEventListener(ename, this.#handler[ename]);
            }, this)
      }, this);
    })

    this.#event_registered['drop'] = false
  }

  unregister_drop_events(){
    DEBUG_DROP && console.log("Unregister Multidrop events")

    this.boxes.forEach((box) => {
      let items = box.querySelectorAll('[draggable=true]');

      items.forEach(function (item) {
        ['dragstart', 'dragend', 'dragover',
          'dragenter', 'dragleave', 'drop'].forEach(
            function(ename){
              item.removeEventListener(ename, this.#handler[ename]);
            }, this)
      }, this);
    })

    this.#event_registered['drop'] = false
  }

  box(el){
    while (el?.parentElement){
      el = el.parentElement
      if (this.boxes.includes(el)){
        return el
      }
    }
  }

  childIndex(el){ /* (DOM order, not flexbox based order) */
    // Direct parents
    //return Array.from(el.parentElement.children).indexOf(el)

    // Indirect parents
    while (el?.parentElement){
      if (this.boxes.includes(el.parentElement)){
        return Array.from(el.parentElement.children).indexOf(el)
      }
      el = el.parentElement
    }
    return -1
  }

  /* Returns matching element to childIndex(el) */
  childElement(el){
    while (el){
      if (this.boxes.includes(el.parentElement)){
        return el
      }
      el = el?.parentElement
    }
  }

  /* Returns subset of selected elements or
   * subset of ancestors of selected elements */
  selected_elements_in_box(box) {
    let e = []
    this.#selected_elements.forEach((s) => {
      if (this.box(s) === box) e.push(this.childElement(s))
    })

    return e
  }

  selected_elements_in_other_boxes(box) {
    let e = []
    this.#selected_elements.forEach((s) => {
      if (this.box(s) !== box) e.push(this.childElement(s))
    })

    return e
  }

  check_for_empty_list() {
    if (this.options.dummy_entry_in_empty_lists === false) return

    this.boxes.forEach((box) => {
      let dummy = box.querySelector('.drag_empty')
      if (box.children.length > 1){
        dummy?.style.removeProperty('display')
        // dummy?.style.setProperty('display', 'none')
      }else{
        dummy?.style.setProperty('display', 'inherit')
      }
    })
  }

}

function default_decorate(el, multidrop){
  //let el = evt.currentTarget
	let elements = multidrop.elements // Array-copy
  DEBUG_DROP && console.log('Undecorate ' + el + ' and selection ' +
    elements)

		//el.style.setProperty('opacity', 0.4)
    elements.forEach(function (el_selected) {
      el_selected.classList.add(multidrop.options.drag_started_class)
    });
}

function default_undecorate(el, multidrop){
  //let el = evt.currentTarget
	let elements = multidrop.elements // Array-copy
  DEBUG_DROP && console.log('Undecorate ' + el + ' and selection ' +
    multidrop.elements)

		//el.style.removeProperty('opacity')
    elements.forEach(function (el_selected) {
      el_selected.classList.remove(multidrop.options.drag_started_class)
    });
}

function default_select_handler(el, multidrop){
  //let el = evt.currentTarget
  DEBUG_DROP && console.log('Select ' + el + ' to selection ' +
    multidrop.elements)

  el.classList.add(multidrop.options.selected_css_class)
}

function default_unselect_handler(el, multidrop){
  //let el = evt.currentTarget
  DEBUG_DROP && console.log('Unselect ' + el + ' of selection ' +
    multidrop.elements)

  el.classList.remove(multidrop.options.selected_css_class)
}

function default_drop_handler(el, permutation, transfererd_elements){
  DEBUG_DROP && console.log(`
  Drag&Drop finished.
  Permutation of existing elements is ${permutation}
  Number of new elements ${transfererd_elements.length}
  `)
}

/*function default_drag_after_handler(){
  DEBUG_DROP && console.log(` Drag completed `)
}*/

function default_drop_after_handler(){
  DEBUG_DROP && console.log(`
  Drop completed and elements sorted in new order.
  `)
}

//Example usage with one list:
/*
var md;
function init_multidrop(){
  md = new Multidrop(document.getElementById('list'), false, {}) 
}

window.addEventListener('DOMContentLoaded', init_multidrop)
*/

//Example usage with two connected lists:
//TODO

export { Multidrop };
