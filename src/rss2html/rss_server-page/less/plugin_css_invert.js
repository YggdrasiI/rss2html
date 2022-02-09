/*
 * Rebuild of CSS's filter: invert(percentage)
 *
 * It provides following change on each rgb channel:
 *     255 - [255*(1-p) + x*(2*p-1)]
 *
 * */
registerPlugin({
	install: function(less, pluginManager, functions) {
		functions.addMultiple({
			'css_invert': function(color1, percentage) {
				// Apply  255 - [255*(1-p) + x*(2*p-1)] on all colors.
				//
				var red = less.functions.functionRegistry.get("red");
				var green = less.functions.functionRegistry.get("green");
				var blue = less.functions.functionRegistry.get("blue");
				var alpha = less.functions.functionRegistry.get("alpha");
				//var rgb = less.functions.functionRegistry.get("rgb");
				var rgba = less.functions.functionRegistry.get("rgba");

				var p = percentage.value; // number
				var r = red(color1);      // obj
				var g = green(color1);    // obj
				var b = blue(color1);     // obj
				r.value = 255 - (255*(1-p) + r.value*(2*p-1));
				g.value = 255 - (255*(1-p) + g.value*(2*p-1));
				b.value = 255 - (255*(1-p) + b.value*(2*p-1));

				//return new tree.Value(rgb(r,g,b));
				return new tree.Value(rgba(r,g,b, alpha(color1)));
			}
		});
	}
})
