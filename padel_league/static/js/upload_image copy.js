let canvas;
let context;
let image_div;
let scale;
let lastScale = 1;
let imageWidth = 0;
let imageHeight = 0;
let scaleFactor;
let canvasRect;
let stop;

let position_of_corner = {
    x: 0,
    y: 0
}

let mousePosition = {
    x:0,
    y:0
}
let lastMousePosition = {
    x:0,
    y:0
}

let center = {
    x: 0,
    y: 0
}

let drawing_point = {
    x: 0,
    y: 0
}

function resetValues(){
    stop = false;
    scale.value = 1;
    lastScale = 1;
    scaleFactor = scale.value/lastScale;
    canvasRect = canvas.getBoundingClientRect();

    position_of_corner = {
        x: 0,
        y: 0
    }

    mousePosition = {
        x:0,
        y:0
    }
    lastMousePosition = {
        x:0,
        y:0
    }

    center = {
        x: 0,
        y: 0
    }

    drawing_point = {
        x: 0,
        y: 0
    }

}

let mouseDown = false;

function mouseDownHandler(e){
    e.stopPropagation();
    e.preventDefault();
    e.stopImmediatePropagation();
    if(e.type=='touchstart'){
        let x;
        let y;
        x = e.touches[0].clientX;
        y = e.touches[0].clientY;
        mousePosition.x = x - canvasRect.left
        mousePosition.y = y - canvasRect.top
    }
    mouseDown = true;
    lastMousePosition.x = mousePosition.x - position_of_corner.x;
    lastMousePosition.y = mousePosition.y - position_of_corner.y;
}

function mouseUpHandler(e){
    e.stopPropagation();
    e.preventDefault();
    e.stopImmediatePropagation();
    mouseDown = false;
}

function mouseMoveHandler(e){
    e.stopPropagation();
    e.preventDefault();
    e.stopImmediatePropagation()
    let x;
    let y;
    if(e.type=='mousemove'){
        x = e.clientX;
        y = e.clientY;
    } else {
        x = e.touches[0].clientX;
        y = e.touches[0].clientY;
    }
    mousePosition.x = x - canvasRect.left
    mousePosition.y = y - canvasRect.top
}

function draw(){
    //Clear the canvas
    context.clearRect(drawing_point.x, drawing_point.y , imageWidth*scaleFactor,  imageHeight*scaleFactor);
    
    //Zoom
    scaleFactor = scale.value/lastScale;

    //Move vector
    if (mouseDown){
        position_of_corner.x = mousePosition.x - lastMousePosition.x;
        position_of_corner.y = mousePosition.y - lastMousePosition.y;
    }

    //Draw
    drawing_point.x = center.x - imageWidth*scaleFactor/2 + position_of_corner.x;
    drawing_point.y = center.y - imageHeight*scaleFactor/2 + position_of_corner.y;
    context.drawImage(image_div, drawing_point.x, drawing_point.y , imageWidth*scaleFactor, imageHeight*scaleFactor);
    if (!stop){
        window.requestAnimationFrame(draw);
    }
}

function init(image,element) {

    let picture_name = element.dataset.picture_name;

    canvas = document.getElementById('canvas_' + picture_name);
    context = canvas.getContext('2d');
    scale = document.getElementById('picture_scale_' + picture_name);
    lastScale = 1;
    imageWidth = 0;
    imageHeight = 0;
    scaleFactor = scale.value/lastScale;
    canvasRect = canvas.getBoundingClientRect();
    stop = false;

    addEventListenersToCanvas(canvas);

    resetValues();
    imageWidth = image.width;
    imageHeight = image.height;
    canvas.width = image.width;
    canvas.height = image.width;
    center.x = canvas.width/2;
    center.y = canvas.height/2;
    canvasRect = canvas.getBoundingClientRect();

    //Make sure canvas is cleared
    context.clearRect(0, 0 , canvas.width,  canvas.height);

    context.drawImage(image, 0, 0 , imageWidth, imageHeight);
    window.requestAnimationFrame(draw);
}

function activateInput(id_name){
    document.getElementById(id_name).click();
}

function inputChangeHandler(element){
    let picture_name = element.dataset.picture_name;
    let image_div = document.getElementById(picture_name);
    image_div.src = "";
    if (element.files[0] == undefined)
        return;
    let reader = new FileReader();
    reader.addEventListener("load", function () {
        image_div.src = reader.result;
        confirmInputPicture(image_div.src,element);
    }, false);
    if (element.files[0]) {
        reader.readAsDataURL(element.files[0]);
    }
}

function inputMultipleChangeHandler(element){
    let existing_images = element.parentNode.querySelectorAll(".final_input_image");
    for (let image of existing_images){
        image.remove();
    }
    let existing_dot_labels = element.parentNode.querySelectorAll(".dot_label");
    for (let dot_label of existing_dot_labels){
        dot_label.remove();
    }

    let picture_name = element.dataset.picture_name;
    let files = element.files;
    let imageInputContainer = document.getElementById('imageInputContainer_' + picture_name);
    imageInputContainer.classList.remove('dropzone-wrapper');
    imageInputContainer.classList.add('added_image');
    for (let i = 0; i < files.length; i++) {
        let reader = new FileReader();
        reader.addEventListener("load", function () {
            let new_image_div = document.createElement('img');
            new_image_div.src = reader.result;
            new_image_div.classList.add('final_input_image');
            new_image_div.id = 'uploaded_image_' + picture_name + '_' + i;
            let active = true;
            if ( i > 0){
                active = false;
                new_image_div.classList.add('inactive_image');
            } 
            createDotLink(new_image_div.id,element,active);
            element.parentNode.insertBefore(new_image_div, element);
        }, false);
        if (files[i]) {
            reader.readAsDataURL(files[i]);
        }
    }
}

function inputEditableChangeHandler(element){
    let picture_name = element.dataset.picture_name;
    image_div = document.getElementById('uploaded_image_' + picture_name);
    image_div.src = "";
    if (element.files[0] == undefined)
        return;
    let reader = new FileReader();
    let modalButton = document.getElementById("modal_button_" +  picture_name);
    modalButton.click();
    reader.addEventListener("load", function () {
        image_div.src = reader.result;
        image_div.onload = function () {
            init(image_div,element);
        }
    }, false);
    if (element.files[0]) {
        reader.readAsDataURL(element.files[0]);
    }
}

function confirmInputPicture(image,ele){
    // it will save locally
    let multipleDataTransfer = new DataTransfer();
    let picture_name = ele.dataset.picture_name;
    let final_image = document.getElementById(picture_name);
    final_image.src = image;
    
    let imageInputContainer = document.getElementById('imageInputContainer_' + picture_name);
    imageInputContainer.classList.remove('dropzone-wrapper');
    imageInputContainer.classList.add('added_image');
    
    for (let child of imageInputContainer.children){
        child.classList.add('disp-none');
    }
    
    final_image.classList.remove('disp-none');
    final_image.classList.add('final_input_image');
    
    let filename = picture_name + '.png';
    var file = dataURLtoFile(image,filename);
    let finalFile = document.getElementById('finalFile_' + picture_name);
    multipleDataTransfer.items.add(file);
    finalFile.files = multipleDataTransfer.files;
}

function createDotLink(image_id,ele,active){
    // it will save locally
    let picture_name = ele.dataset.picture_name;
    let gallery = document.getElementById('galery_' + picture_name);
    let dotLabel = document.createElement('div');
    dotLabel.classList.add('dot_label');
    if (active){
        dotLabel.classList.add('active_dot_label');
    }
    gallery.appendChild(dotLabel);
    
    dotLabel.addEventListener('click',function(){
        dotClick(dotLabel,image_id);
    });
    gallery.classList.remove('disp-none');
    if (!gallery.classList.contains('image_galery')){
        gallery.classList.add('image_galery');
    }
}

function dotClick(dotLabel,image_id){
    let currentActiveDotLabel = document.querySelector(".active_dot_label");
    if (currentActiveDotLabel) {
        currentActiveDotLabel.classList.remove("active_dot_label");
    }
    dotLabel.classList.add('active_dot_label');
    let currentActiveElement = document.querySelector(".final_input_image:not(.inactive_image)");
    if (currentActiveElement) {
        currentActiveElement.classList.add("inactive_image");
    }

    let image = document.getElementById(image_id);
    if (image.classList.contains("inactive_image")) {
        image.classList.remove("inactive_image");
    }    
}

function rechoseImage(element_id){
    let element = document.getElementById(element_id);
    element.click();
}

function confirmEditableInputPicture(ele){
    let multipleDataTransfer = new DataTransfer();
    stop = true;
    var image = canvas.toDataURL();
    // it will save locally
    let picture_name = ele.getAttribute("name");
    let final_image = document.getElementById(picture_name);
    final_image.src = image;

    let imageInputContainer = document.getElementById('imageInputContainer_' + picture_name);
    imageInputContainer.classList.remove('dropzone-wrapper');
    imageInputContainer.classList.add('added_image');

    for (let child of imageInputContainer.children){
        child.classList.add('disp-none');
    }

    final_image.classList.remove('disp-none');
    final_image.classList.add('final_input_image');

    let filename = picture_name + '.png';
    var file = dataURLtoFile(image,filename);
    let finalFile = document.getElementById('finalFile_'+picture_name);
    multipleDataTransfer.items.add(file);
    finalFile.files = multipleDataTransfer.files;
}

function dataURLtoFile(dataurl, filename) {
    var arr = dataurl.split(','),
        mime = arr[0].match(/:(.*?);/)[1],
        bstr = atob(arr[1]), 
        n = bstr.length, 
        u8arr = new Uint8Array(n);
        
    while(n--){
        u8arr[n] = bstr.charCodeAt(n);
    }
    
    return new File([u8arr], filename, {type:mime});
}

function addEventListenersToCanvas(canvas){
    canvas.addEventListener('mousedown', mouseDownHandler, false);
    canvas.addEventListener('mouseup', mouseUpHandler, false);
    canvas.addEventListener('mousemove', mouseMoveHandler, false);
    canvas.addEventListener('mouseover', mouseUpHandler, false);
    canvas.addEventListener('touchstart', mouseDownHandler, {passive: false});
    canvas.addEventListener('touchend', mouseUpHandler, false);
    canvas.addEventListener('touchmove', mouseMoveHandler, {passive: false});
}

/* window.addEventListener('load', function(e){
    let isPhone = ( window.innerWidth <= 500 ) && ( window.innerHeight <= 900 )
    let modal_content = document.getElementsByClassName("modal_content")[0];
    if (isPhone){
        modal_content.style.width = "90.5vw"; 
        image_div.style.height = "90vw";
    } else {
        modal_content.style.width = "50.1vh";
        image_div.style.width = "50vh";
    }
}); */

function dragoverDragAndDrop(event,element) {
    event.preventDefault();
    event.stopPropagation();
    element.classList.add("dragover");
}

function dragleaveDragAndDrop(event,element) {
    event.preventDefault();
    event.stopPropagation();
    element.classList.remove("dragover");
}
