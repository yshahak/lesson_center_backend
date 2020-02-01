'use strict';
const CACHE_NAME = 'flutter-app-cache';
const RESOURCES = {
  "/index.html": "e927ffa172f0ee8bf95f7e7c81fbf060",
"/main.dart.js": "75b9f4e7e518e7d0332590cbdc503a3b",
"/lessons.db": "14b966309470d515907d8c5a7a48df60",
"/sql-wasm.js": "81d1b03c876e7e4e239052a7869d5d6d",
"/assets/LICENSE": "d1a29a7064e77088393f6094e0b4116a",
"/assets/AssetManifest.json": "cf2dae5185c2af1773e8176ccddd6765",
"/assets/FontManifest.json": "01700ba55b08a6141f33e168c4a6c22f",
"/assets/packages/cupertino_icons/assets/CupertinoIcons.ttf": "9a62a954b81a1ad45a58b9bcea89b50b",
"/assets/fonts/MaterialIcons-Regular.ttf": "56d3ffdef7a25659eab6a68a3fbfaf16",
"/assets/assets/lessons.db": "14b966309470d515907d8c5a7a48df60",
"/sql-wasm.wasm": "b01552bc79c0b957d4228839bb9b74bf"
};

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (cacheName) {
      return caches.delete(cacheName);
    }).then(function (_) {
      return caches.open(CACHE_NAME);
    }).then(function (cache) {
      return cache.addAll(Object.keys(RESOURCES));
    })
  );
});

self.addEventListener('fetch', function (event) {
  event.respondWith(
    caches.match(event.request)
      .then(function (response) {
        if (response) {
          return response;
        }
        return fetch(event.request, {
          credentials: 'include'
        });
      })
  );
});
