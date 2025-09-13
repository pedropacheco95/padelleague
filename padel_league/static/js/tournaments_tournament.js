document.getElementById('general_information_button').addEventListener('click',activateDataTabs);
document.getElementById('matches_information_button').addEventListener('click',activateDataTabs);
document.getElementById('calendar_button').addEventListener('click',activateDataTabs);
let add_game_button = document.getElementById('add_game_button')
if (add_game_button){
    add_game_button.addEventListener('click',activateDataTabs);
}

function activateDataTabs(button_element){
    for (element of document.getElementsByClassName('c-tor-header__item--active')){
        element.classList.remove('c-tor-header__item--active');
    }
    for (element of document.getElementsByClassName('is-visible')){
        element.classList.remove('is-visible');
    }

    button_element.currentTarget.parentNode.classList.add('c-tor-header__item--active');
    if (button_element.currentTarget.id == 'general_information_button'){
        document.getElementById('general_information_tab').classList.add('is-visible');
    }
    if (button_element.currentTarget.id == 'matches_information_button'){
        document.getElementById('matches_information_tab').classList.add('is-visible');
    }
    if (button_element.currentTarget.id == 'calendar_button'){
        document.getElementById('calendar_tab').classList.add('is-visible');
    }
    if (button_element.currentTarget.id == 'add_game_button'){
        document.getElementById('add_game_tab').classList.add('is-visible');
    }
}

function addGraph(player_id){
    var row = document.getElementById("graph_row");
    if (row){
        row.remove();
    }
    var xValues = [];
    var yValues = [];
    xValues = [...points_by_matchweeks[player_id].x]
    yValues = [...points_by_matchweeks[player_id].y]
    //Add buffers to lool better
    xValues.unshift(0)
    xValues.push(xValues[xValues.length - 1]+1)
    yValues.unshift(0)
    yValues.push(0)

    var player_row = document.getElementById(player_id);
    var table = document.getElementById('classification_table');

    var row = document.createElement('tr');
    row.style.backgroundColor= 'rgba(217,226,228,.6)';
    row.setAttribute('id','graph_row');
    var column = document.createElement('td');
    column.colSpan = table.rows[0].cells.length
    var title = document.createElement('h3');
    title.innerText = 'Evolução por jornada';
    var canvas = document.createElement('canvas');
    canvas.id = 'myChart';
    canvas.style.width = table.width;
    canvas.style.height = 0.5*window.innerHeight

    column.appendChild(title)
    column.appendChild(canvas)
    row.appendChild(column)
    insertAfter(row,player_row)

    new Chart("myChart", {
        type: "line",
        data: {
            labels: xValues,
            datasets: [{
                fill: false,
                lineTension: 0,
                backgroundColor: "rgba(0,0,255,1.0)",
                borderColor: "rgba(0,0,255,0.1)",
                data: yValues
            }]
        },
        options: {
            legend: {display: false},
            scales: {
                yAxes: [{ticks: {min: 0, max:10}}],
            }
        }
    });
}

function removeGraph(){
    var row = document.getElementById("graph_row");
    if (row){
        row.remove();
    }
}

function insertAfter(newNode, existingNode) {
    existingNode.parentNode.insertBefore(newNode, existingNode.nextSibling);
}
