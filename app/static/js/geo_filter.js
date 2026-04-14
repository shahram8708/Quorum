(() => {
  const sortSelect = document.querySelector('select[name="sort"]');
  if (!sortSelect) return;

  sortSelect.addEventListener('change', () => {
    if (sortSelect.value !== 'near_me') return;
    if (!navigator.geolocation) {
      alert('Enable location to see nearby projects.');
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const url = new URL(window.location.href);
        url.searchParams.set('lat', position.coords.latitude.toFixed(6));
        url.searchParams.set('lon', position.coords.longitude.toFixed(6));
        window.location.href = url.toString();
      },
      () => {
        alert('Enable location to see nearby projects.');
      }
    );
  });
})();
