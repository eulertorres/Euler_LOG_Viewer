(function () {
    const aircraftName = "$AIRCRAFT_MARKER_NAME";
    const windName = "$WIND_MARKER_NAME";

    if (typeof window.updateMarkers !== 'function') {
        window.updateMarkers = function (lat, lon, aircraft_yaw, wind_dir, wind_speed) {
            const aircraftMarker = window[aircraftName];
            const windMarker = window[windName];

            if (aircraftMarker && typeof aircraftMarker.setLatLng === 'function') {
                const newLatLng = L.latLng(lat, lon);
                aircraftMarker.setLatLng(newLatLng);
                const aircraftImg = document.getElementById('aircraft-img');
                if (aircraftImg) {
                    aircraftImg.style.transform = 'rotate(' + aircraft_yaw + 'deg)';
                }
            }

            if (windMarker && typeof windMarker.setLatLng === 'function') {
                const newLatLngWind = L.latLng(lat, lon);
                windMarker.setLatLng(newLatLngWind);
                const windImg = document.getElementById('wind-arrow-img');
                if (windImg) {
                    const windRotation = wind_dir;
                    const opacity = 0.8 + (Math.min(wind_speed, 20) / 20) * 0.7;
                    const scale = 0.7 + (Math.min(wind_speed, 15) / 15);
                    windImg.style.opacity = opacity.toFixed(2);
                    windImg.style.transform = 'rotate(' + windRotation + 'deg) scale(' + scale.toFixed(2) + ')';
                }
            }
        };
        console.log('DEBUG JS: Função global updateMarkers(lat, lon, yaw, wind_dir, wind_speed) definida.');
    }
})();
