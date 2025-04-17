var isMobile = ('ontouchstart' in document.documentElement);
let currentDivisionIndex = 0;

function duplicateElement(element){
    var newElement = element.cloneNode(true);
    element.parentNode.insertBefore(newElement, element.nextSibling);
}

function duplicateInputElement(element){
    var newElement = element.cloneNode(true);
    newElement.value = ""
    element.parentNode.insertBefore(newElement, element.nextSibling);
}

function linkToDatasetHref(element){
    window.location.href = element.dataset.href;
}

function changeDivision(editionId, direction) {
    const blocks = document.querySelectorAll(`[id^="division-"]`);
    const total = blocks.length;

    if (blocks.length === 0) return;

    blocks[currentDivisionIndex].style.display = 'none';
    currentDivisionIndex = (currentDivisionIndex + direction + total) % total;
    blocks[currentDivisionIndex].style.display = 'block';
}