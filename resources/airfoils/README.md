# Bundled aerofoil coordinates

Numerical geometry from the UIUC Airfoil Data Site, downloaded 2026-09-29.
Coordinates have chord = 1, in Selig order: upper trailing edge, nose, lower
trailing edge. Source coordinate values are unchanged.

* Clark Y: https://m-selig.ae.illinois.edu/ads/coord_seligFmt/clarky.dat
* Selig S1223: https://m-selig.ae.illinois.edu/ads/coord/s1223.dat
* Eppler E850: https://m-selig.ae.illinois.edu/ads/coord_seligFmt/e850.dat

The [UIUC database](https://m-selig.ae.illinois.edu/ads/coord_database.html)
identifies S1223 as a high-lift low-Reynolds-number section and E850 as a
propeller section. See [S1223 tests](https://m-selig.ae.illinois.edu/uiuc_lsat/s1223/s1223_liftcm.html).
NACA 0012, 2412 and 4415 are generated analytically. NACA 4415 is a slow-flight
starting point, not a claim of tested gentle stall. Geometry alone cannot
determine stall speed or handling.
