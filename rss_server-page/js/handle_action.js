/*
 * To catch clicks on action links in 'media section'.
 * 
 * (If Javascript is disabled it will still follow the link. This is also ok)
 */

function action_link(el){
	call_link(el.href);
	console.log("Action url called:" + el.href);
	//return false; //redundant
}

function call_link(url){
	/* Trigger simple http request */
	var xhr = new XMLHttpRequest();
	xhr.open("GET", url, true);
	xhr.responseType = "document";

	xhr.onload = function (oEvent) {
		if (xhr.readyState === xhr.DONE && xhr.status === 200) {
			console.log(xhr.response, xhr.responseXML);

			// Extract status message
			msg = xhr.responseXML.getElementById("feedBody");
			console.log("Action handled" + msg.innerText);
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
				link.addEventListener("click", function(evt){
					evt.preventDefault();
					action_link(link);
				});
			}
		}
    console.log("Action handlers added.")
}


window.addEventListener("load", add_action_event_handler);
