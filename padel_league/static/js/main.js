var isMobile = ('ontouchstart' in document.documentElement);

function duplicateElement(element){
    var newElement = element.cloneNode(true);
    element.parentNode.insertBefore(newElement, element.nextSibling);
}

function duplicateInputElement(element){
    var newElement = element.cloneNode(true);
    newElement.value = ""
    element.parentNode.insertBefore(newElement, element.nextSibling);
}