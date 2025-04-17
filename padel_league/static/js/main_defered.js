let clickableRows = document.getElementsByClassName('clickable-row');

for (let clickableRow of clickableRows) {
    clickableRow.addEventListener('click', function() {
        window.location = this.dataset.href;
    });
}