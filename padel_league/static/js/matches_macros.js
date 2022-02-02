function chooseMatchweek(selectObject){
    var matchweek = selectObject.value;
    location.replace(matchweek_url.replace(/.$/,matchweek)) 
}