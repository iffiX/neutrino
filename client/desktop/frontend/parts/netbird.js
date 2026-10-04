// NetBird's part of the window: its engine's name, its way in, and its row
// of About. The page inlines every file of parts/ before app.js; the
// mainland tree holds none.
window.NEUTRINO_PARTS = (window.NEUTRINO_PARTS || []).concat([{
  overlayTitles: { netbird: 'NetBird' },
  throughWays: ['netbird'],
  carried: [
    { name: 'NetBird', key: 'netbird', licence: 'BSD-3-Clause',
      repository: 'https://github.com/netbirdio/netbird', tag: 'v{version}' },
  ],
}]);
