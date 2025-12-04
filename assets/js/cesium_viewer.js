(function () {
    const terrainProvider = new Cesium.EllipsoidTerrainProvider();
    const viewer = new Cesium.Viewer('cesiumContainer', {
        animation: false,
        timeline: false,
        shouldAnimate: false,
        terrainProvider: terrainProvider,
        imageryProvider: undefined,
        baseLayerPicker: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        geocoder: false,
        fullscreenButton: false,
        homeButton: false,
        infoBox: false,
        selectionIndicator: false
    });

    viewer.scene.globe.enableLighting = true;
    viewer.clock.shouldAnimate = false;

    const imageryConfigsArray = $IMAGERY_CONFIG_JSON;
    const imageryConfigs = imageryConfigsArray.reduce((acc, cfg) => {
        acc[cfg.key] = cfg;
        return acc;
    }, {});

    const defaultImageryKey = $DEFAULT_IMAGERY_KEY;
    const samples = $SAMPLES_JSON;
    const modePaths = $MODE_PATHS_JSON;
    const sampleTimes = Array.isArray(samples)
        ? samples.map(s => (s && Number.isFinite(s.timeMs)) ? s.timeMs : null)
        : [];

    const routePositions = Array.isArray(samples)
        ? samples.map(s => (s && Number.isFinite(s.lat) && Number.isFinite(s.lon))
            ? { lat: s.lat, lon: s.lon, alt: Number.isFinite(s.alt) ? s.alt : 0.0 }
            : null)
        : [];

    let startJulian = undefined;
    let stopJulian = undefined;

    function buildTilingScheme(cfg) {
        if (cfg.tilingScheme === 'geographic') {
            return new Cesium.GeographicTilingScheme();
        }
        return new Cesium.WebMercatorTilingScheme();
    }

    function createImageryProvider(cfg) {
        return new Cesium.UrlTemplateImageryProvider({
            url: cfg.url,
            credit: cfg.credit || '',
            tilingScheme: buildTilingScheme(cfg),
            maximumLevel: Number.isFinite(cfg.maximumLevel) ? cfg.maximumLevel : undefined
        });
    }

    function applyImageryLayer(key) {
        const cfg = imageryConfigs[key] || imageryConfigs[defaultImageryKey];
        if (!cfg) {
            return;
        }
        if (window.__currentBaseLayer) {
            viewer.imageryLayers.remove(window.__currentBaseLayer, true);
        }
        window.__currentBaseLayer = viewer.imageryLayers.addImageryProvider(
            createImageryProvider(cfg),
            0
        );
        return cfg;
    }

    applyImageryLayer(defaultImageryKey);
    window.setImageryLayer = function(key) {
        return applyImageryLayer(key);
    };

    const modePolylineCollection = viewer.scene.primitives.add(new Cesium.PolylineCollection());
    function colorFromRgb(rgb, alpha) {
        const r = Number.isFinite(rgb?.[0]) ? rgb[0] : 33;
        const g = Number.isFinite(rgb?.[1]) ? rgb[1] : 150;
        const b = Number.isFinite(rgb?.[2]) ? rgb[2] : 243;
        return Cesium.Color.fromBytes(r, g, b, alpha ?? 200);
    }

    function toCartesianFromPoints(list) {
        const arr = [];
        for (const p of list || []) {
            if (!Number.isFinite(p?.lon) || !Number.isFinite(p?.lat)) continue;
            arr.push(p.lon, p.lat, Number.isFinite(p.alt) ? p.alt : 0.0);
        }
        return arr.length ? Cesium.Cartesian3.fromDegreesArrayHeights(arr) : [];
    }

    try {
        if (Array.isArray(modePaths)) {
            modePaths.forEach(seg => {
                const positions = toCartesianFromPoints(seg?.points);
                if (positions.length >= 2) {
                    modePolylineCollection.add({
                        positions,
                        width: 3,
                        material: Cesium.Material.fromType('Color', {
                            color: colorFromRgb(seg?.color, 235)
                        })
                    });
                }
            });
        }
    } catch (err) {
        console.error('Mode path render fallback', err);
    }

    const scratchHPR = new Cesium.HeadingPitchRoll();
    const defaultPosition = Cesium.Cartesian3.fromDegrees(-47.9, -15.7, 1000.0);
    const aircraftEntity = viewer.entities.add({
        id: 'aircraft-model',
        name: 'Aeronave',
        position: defaultPosition,
        model: {
            uri: $PLANE_LITERAL,
            minimumPixelSize: 80,
            maximumScale: 200,
            runAnimations: true
        },
        orientation: Cesium.Transforms.headingPitchRollQuaternion(
            defaultPosition,
            new Cesium.HeadingPitchRoll()
        )
    });

    viewer.trackedEntity = aircraftEntity;

    const hudLat = document.getElementById('hud-lat');
    const hudLon = document.getElementById('hud-lon');
    const hudAlt = document.getElementById('hud-alt');
    const hudPitch = document.getElementById('hud-pitch');
    const hudRoll = document.getElementById('hud-roll');

    function updateHud(lat, lon, alt, pitchDeg, rollDeg) {
        hudLat.textContent = Number.isFinite(lat) ? lat.toFixed(6) : '--';
        hudLon.textContent = Number.isFinite(lon) ? lon.toFixed(6) : '--';
        hudAlt.textContent = Number.isFinite(alt) ? alt.toFixed(1) : '--';
        hudPitch.textContent = Number.isFinite(pitchDeg) ? pitchDeg.toFixed(1) : '--';
        hudRoll.textContent = Number.isFinite(rollDeg) ? rollDeg.toFixed(1) : '--';
    }

    function radiansOrZero(valueDeg) {
        return Cesium.Math.toRadians(Number.isFinite(valueDeg) ? valueDeg : 0.0);
    }

    const headingOffset = Cesium.Math.toRadians(-90.0);
    function applySample(sample) {
        if (!sample || !Number.isFinite(sample.lat) || !Number.isFinite(sample.lon)) {
            return;
        }
        const safeAlt = Number.isFinite(sample.alt) ? sample.alt : 0.0;
        const position = Cesium.Cartesian3.fromDegrees(sample.lon, sample.lat, safeAlt);
        aircraftEntity.position = position;
        scratchHPR.heading = radiansOrZero(sample.heading) + headingOffset;
        scratchHPR.pitch = radiansOrZero(sample.pitch);
        scratchHPR.roll = radiansOrZero(sample.roll);
        aircraftEntity.orientation = Cesium.Transforms.headingPitchRollQuaternion(position, scratchHPR);
        updateHud(sample.lat, sample.lon, safeAlt, sample.pitch, sample.roll);
    }

    window.centerCameraOnAircraft = function() {
        if (!aircraftEntity) {
            return;
        }
        if (window.__followEnabled !== false) {
            viewer.trackedEntity = aircraftEntity;
        }
        viewer.flyTo(aircraftEntity, {
            duration: 0.6,
            offset: new Cesium.HeadingPitchRange(0.0, -0.5, 150.0)
        });
    };

    window.setFollowMode = function(enabled) {
        window.__followEnabled = !!enabled;
        viewer.trackedEntity = enabled ? aircraftEntity : undefined;
    };

    const completedPath = viewer.entities.add({
        polyline: {
            positions: [],
            width: 4,
            material: new Cesium.PolylineGlowMaterialProperty({
                glowPower: 0.12,
                color: Cesium.Color.WHITE.withAlpha(0.95)
            })
        }
    });

    const upcomingPath = viewer.entities.add({
        polyline: {
            positions: [],
            width: 3,
            material: Cesium.Color.WHITE.withAlpha(0.25)
        }
    });

    function toCartesian(pts) {
        const arr = [];
        for (const p of pts) {
            if (!p) continue;
            arr.push(p.lon, p.lat, p.alt);
        }
        return arr.length ? Cesium.Cartesian3.fromDegreesArrayHeights(arr) : [];
    }

    function updateRouteProgress(index) {
        if (!Array.isArray(routePositions) || !routePositions.length) {
            return;
        }
        const clamped = Math.max(0, Math.min(routePositions.length, index + 1));
        const done = routePositions.slice(0, clamped);
        const nextSegment = routePositions.slice(Math.max(0, clamped - 1));
        completedPath.polyline.positions = toCartesian(done);
        upcomingPath.polyline.positions = toCartesian(nextSegment);
    }

    function julianFromMs(ms) {
        return Cesium.JulianDate.fromDate(new Date(ms));
    }

    function findIndexForJulian(jd) {
        if (!sampleTimes.length) return 0;
        const currentMs = Cesium.JulianDate.toDate(jd).getTime();
        for (let i = 0; i < sampleTimes.length; i++) {
            const t = sampleTimes[i];
            if (t === null) continue;
            const next = sampleTimes[Math.min(sampleTimes.length - 1, i + 1)];
            if (currentMs <= (next ?? currentMs)) {
                return i;
            }
        }
        return sampleTimes.length - 1;
    }

    function clampIndex(idx) {
        return Math.max(0, Math.min(samples.length - 1, Number(idx) || 0));
    }

    let currentIndex = 0;
    function applyIndex(idx) {
        if (!Array.isArray(samples) || !samples.length) return;
        const clamped = clampIndex(idx);
        if (clamped === currentIndex && !viewer.clock.shouldAnimate) return;
        currentIndex = clamped;
        const sample = samples[clamped];
        if (sample) {
            applySample(sample);
            if (window.__followEnabled !== false) {
                viewer.trackedEntity = aircraftEntity;
            }
        }
        updateRouteProgress(clamped);
        window.__currentTimelineIndex = clamped;
    }

    window.setTimelineIndex = function(index) {
        if (!sampleTimes.length) return;
        const clamped = clampIndex(index);
        const t = sampleTimes[clamped];
        if (Number.isFinite(t)) {
            viewer.clock.shouldAnimate = false;
            viewer.clock.currentTime = julianFromMs(t);
            applyIndex(clamped);
        }
    };

    if (Array.isArray(samples) && samples.length) {
        const firstValidTime = sampleTimes.find(t => t !== null);
        const lastValidTime = [...sampleTimes].reverse().find(t => t !== null);
        if (Number.isFinite(firstValidTime) && Number.isFinite(lastValidTime)) {
            startJulian = julianFromMs(firstValidTime);
            stopJulian = julianFromMs(lastValidTime);
            viewer.clock.startTime = startJulian.clone();
            viewer.clock.stopTime = stopJulian.clone();
            viewer.clock.currentTime = startJulian.clone();
            viewer.clock.clockRange = Cesium.ClockRange.CLAMPED;
            viewer.clock.shouldAnimate = false;
        }

        const initialSample = samples.find(s => !!s);
        if (initialSample) {
            const startPosition = Cesium.Cartesian3.fromDegrees(initialSample.lon, initialSample.lat, initialSample.alt || 0.0);
            aircraftEntity.position = startPosition;
            aircraftEntity.orientation = Cesium.Transforms.headingPitchRollQuaternion(
                startPosition,
                new Cesium.HeadingPitchRoll()
            );
        }

        viewer.trackedEntity = aircraftEntity;
        window.__followEnabled = true;
        viewer.clock.onTick.addEventListener(function(clock) {
            if (!sampleTimes.length) return;
            const idx = findIndexForJulian(clock.currentTime);
            if (idx !== currentIndex || clock.shouldAnimate) {
                applyIndex(idx);
            }
        });
    } else {
        viewer.trackedEntity = aircraftEntity;
        window.__followEnabled = true;
    }

    window.__cesiumViewerReady = true;
})();
