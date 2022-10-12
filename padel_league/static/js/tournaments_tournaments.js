let tournamentContainer = document.getElementsByClassName('tournament__container')

for (let tournament of tournamentContainer){
    tournament.addEventListener('click',linkToTournament,false);
}

function linkToTournament(event){
    let tournament = getElementWithClass(event.path,'tournament__container');
    window.location = tournament.dataset.href;
    return false;
}

function getElementWithClass(array,elementClass){
    for (let element of array){
        if (element.classList.contains(elementClass)){
            return element;
        }
    }
    return null;
}