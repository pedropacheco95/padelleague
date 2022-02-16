function chooseMatchweek(selectObject){
    var matchweek = selectObject.value;
    location.replace(matchweek_url.replace(/.$/,matchweek)) 
}

function chooseDivision(selectObject){
    var division_id = selectObject.value;
    location.replace(division_url.replace(/.$/,division_id)) 
}
