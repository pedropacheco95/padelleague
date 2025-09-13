let modal = document.getElementById("Modal");
let btn = document.getElementById("modalActivation");
let span = document.getElementsByClassName("closeModal");

btn.onclick = function() {
    modal.style.display = "block";
}

for (let element of span) {
    element.onclick = function() {
        modal.style.display = "none";
    }
}

window.onclick = function(event) {
    if (event.target == modal) {
        modal.style.display = "none";
    }
}
