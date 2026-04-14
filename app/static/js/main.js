(() => {
  const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  [...tooltipTriggerList].forEach((el) => new bootstrap.Tooltip(el));

  const flashAlerts = document.querySelectorAll('.alert');
  flashAlerts.forEach((alertEl) => {
    setTimeout(() => {
      const alert = bootstrap.Alert.getOrCreateInstance(alertEl);
      alert.close();
    }, 6000);
  });

  const homePath = window.location.pathname === '/';
  if (homePath && navigator.geolocation && !window.location.search.includes('lat=')) {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const url = new URL(window.location.href);
        url.searchParams.set('lat', position.coords.latitude.toFixed(6));
        url.searchParams.set('lon', position.coords.longitude.toFixed(6));
        window.location.replace(url.toString());
      },
      () => {
        // Silent fallback to default widget.
      },
      {timeout: 3000}
    );
  }
})();
