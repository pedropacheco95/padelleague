let canvas = document.getElementById('canvas');
let confirm_chosen_picture = document.getElementById('confirm_chosen_picture');
let final_image = document.getElementById('upload-aphoto');
let context = canvas.getContext('2d');
let image_div = document.getElementById('uploaded_image');
let scale = document.getElementById('picture_scale');
let modalButton = document.getElementById("modalActivation");
let lastScale = 1;
let imageWidth = 0;
let imageHeight = 0;
let scaleFactor = scale.value/lastScale;
let canvasRect = canvas.getBoundingClientRect();
let stop = false;
const multipleDataTransfer = new DataTransfer();

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
    e.stopImmediatePropagation();
    mouseDown = false;
}

function mouseMoveHandler(e){
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
    //lastScale = scale.value;
    //context.scale(scaleFactor, scaleFactor);

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

function init(image) {
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

$(document).on('click', '#upload-aphoto', function () {
    document.getElementById('selectedFile').click();
});

$('#selectedFile').change(function () {
    image_div.src = "";
    if (this.files[0] == undefined)
        return;
    let reader = new FileReader();
    modalButton.click();
    reader.addEventListener("load", function () {
        image_div.src = reader.result;
        image_div.onload = function () {
            init(image_div);
        }

        $('#selectedFile').val('');
    }, false);
    if (this.files[0]) {
        reader.readAsDataURL(this.files[0]);
    }
    
});

$('#myModal').on('shown.bs.modal', function () {
    $('#myInput').trigger('focus')
})

$('#confirm_chosen_picture').click(function () {
    stop = true;
    var image = canvas.toDataURL();
     // it will save locally
    final_image.src = image;


    var file = dataURLtoFile(image,'player_picture.png');
    let finalFile = document.getElementById('finalFile');
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    finalFile.files = dataTransfer.files;
});

$('#confirm_chosen__product_picture').click(function () {
    stop = true;
    var image = canvas.toDataURL();
     // it will save locally
    final_image.src = image;

    //create image element
    var img = document.createElement('img');
    let galery = document.getElementById('galery');
    img.src = image;
    galery.appendChild(img);

    let filename = 'product_picture' + galery.childElementCount + '.png';


    var file = dataURLtoFile(image,filename);
    let finalFile = document.getElementById('finalFile');
    multipleDataTransfer.items.add(file);
    finalFile.files = multipleDataTransfer.files;
});

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

canvas.addEventListener('mousedown', mouseDownHandler, false);
canvas.addEventListener('mouseup', mouseUpHandler, false);
canvas.addEventListener('mousemove', mouseMoveHandler, false);
canvas.addEventListener('mouseover', mouseUpHandler, false);
canvas.addEventListener('touchstart', mouseDownHandler, false);
canvas.addEventListener('touchend', mouseUpHandler, false);
canvas.addEventListener('touchmove', mouseMoveHandler, false);

window.addEventListener('load', function(e){
    let isPhone = ( window.innerWidth <= 500 ) && ( window.innerHeight <= 900 )
    let modal_content = document.getElementsByClassName("modal_content")[0];
    if (isPhone){
        modal_content.style.width = "90.5vw"; 
        image_div.style.height = "90vw";
    } else {
        modal_content.style.width = "50.1vh";
        image_div.style.width = "50vh";
    }
});