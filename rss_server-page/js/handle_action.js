/*
 * To catch clicks on action links in 'media section'.
 * 
 * (If Javascript is disabled it will still follow the link. This is also ok)
 */

function action_link(el){
	call_link(el.href, el.parentElement.parentElement.parentElement);
	console.log("Action url called:" + el.href);
}

function give_feedback(el, parent_handler){
  // Gives feedback if text string is not empty.
	// The handler is stoped until the normal style is restored

	var timeout = 3000;
	var _skip_click = function (evt) {evt.preventDefault();}
	var col = el.style.color;

	el.style.color = "#666666";
	el.removeEventListener("click", parent_handler);
	el.addEventListener("click", _skip_click);

	setTimeout(function() {
		el.style.color = col;
		el.removeEventListener("click", _skip_click);
		el.addEventListener("click", parent_handler);
	}, timeout)

}

function call_link(url, feedback_element){
	/* Trigger simple http request */
	var xhr = new XMLHttpRequest();
	xhr.open("GET", url, true);
	xhr.responseType = "document";

	xhr.onload = function (oEvent) {
		if (xhr.readyState === xhr.DONE && xhr.status === 200) {
			console.log(xhr.response, xhr.responseXML);

			// Extract status message
			msg = xhr.responseXML.getElementById("feedBody");
			console.log(msg.innerText);

			// Print status message text
			var textnode = document.createTextNode(msg.innerText);
			if (feedback_element.lastChild.nodeType == 3){
				feedback_element.replaceChild(textnode, feedback_element.lastChild);
			}else{
				feedback_element.appendChild(textnode);
			}
		}else{
			console.log("Action request error: " + String(xhr.status) );
		}
	};

	xhr.send(null);
}


/* Add event listener here but not in html page.
 * Content Security Policy does not allow inline javascript.
*/
function add_action_event_handler(){
    for( const enclosure of
			document.getElementsByClassName("enclosure_actions")
		){
			for( const link of enclosure.getElementsByTagName("a")){
				link.addEventListener("click", function _listener(evt){
					evt.preventDefault();
					action_link(link);
					give_feedback(link, _listener);
				});
			}
		}
    console.log("Action handlers added.")
}


window.addEventListener("load", add_action_event_handler);
