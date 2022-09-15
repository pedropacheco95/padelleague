var isMobile = ('ontouchstart' in document.documentElement);

if (isMobile){
    window.addEventListener('load',(event)=>{
        $('html, body').animate({
            scrollTop: $('#site-container').offset().top
        }, 'slow');
    });
}

function duplicateElement(element){
    var newElement = element.cloneNode(true);
    element.parentNode.insertBefore(newElement, element.nextSibling);
}

function duplicateInputElement(element){
    var newElement = element.cloneNode(true);
    newElement.value = ""
    element.parentNode.insertBefore(newElement, element.nextSibling);
}