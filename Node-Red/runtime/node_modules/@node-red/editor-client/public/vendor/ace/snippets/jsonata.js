ace.define("ace/snippets/jsonata",["require","exports","module"],function(s,n,a){"use strict";var t="";for(var e in jsonata.functions)jsonata.functions.hasOwnProperty(e)&&(t+="# "+e+`
snippet `+e+`
	`+jsonata.getFunctionSnippet(e)+`
`);n.snippetText=t,n.scope="jsonata"});
