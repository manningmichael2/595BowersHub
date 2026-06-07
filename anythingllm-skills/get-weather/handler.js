module.exports.runtime = {
  handler: async function ({ location }) {
    try {
      // Default coordinates: Clawson, MI (48017)
      let lat = 42.53;
      let lon = -83.15;
      let locationName = "Clawson, MI";

      // If a location was provided, geocode it first
      if (location && location.trim()) {
        const geoUrl = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(location.trim())}&count=1&language=en&format=json`;
        const geoResponse = await fetch(geoUrl);

        if (geoResponse.ok) {
          const geoData = await geoResponse.json();
          if (geoData.results && geoData.results.length > 0) {
            lat = geoData.results[0].latitude;
            lon = geoData.results[0].longitude;
            locationName = geoData.results[0].name;
            if (geoData.results[0].admin1) {
              locationName += `, ${geoData.results[0].admin1}`;
            }
          } else {
            return `Could not find location: "${location}". Try a different city name.`;
          }
        }
      }

      // Fetch current weather + 7-day forecast
      const weatherUrl = [
        `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}`,
        `&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_gusts_10m`,
        `&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max`,
        `&temperature_unit=fahrenheit`,
        `&wind_speed_unit=mph`,
        `&precipitation_unit=inch`,
        `&timezone=America%2FDetroit`,
        `&forecast_days=7`
      ].join("");

      const response = await fetch(weatherUrl);

      if (!response.ok) {
        return `Error fetching weather: HTTP ${response.status}`;
      }

      const data = await response.json();

      // Weather code descriptions
      const weatherCodes = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail"
      };

      const current = data.current;
      const daily = data.daily;

      const result = {
        location: locationName,
        current: {
          temperature: `${current.temperature_2m}°F`,
          feels_like: `${current.apparent_temperature}°F`,
          humidity: `${current.relative_humidity_2m}%`,
          conditions: weatherCodes[current.weather_code] || `Code ${current.weather_code}`,
          wind: `${current.wind_speed_10m} mph`,
          wind_gusts: `${current.wind_gusts_10m} mph`,
          precipitation: `${current.precipitation} in`
        },
        forecast: daily.time.map((date, i) => ({
          date: date,
          high: `${daily.temperature_2m_max[i]}°F`,
          low: `${daily.temperature_2m_min[i]}°F`,
          conditions: weatherCodes[daily.weather_code[i]] || `Code ${daily.weather_code[i]}`,
          precipitation: `${daily.precipitation_sum[i]} in`,
          rain_chance: `${daily.precipitation_probability_max[i]}%`,
          wind: `${daily.wind_speed_10m_max[i]} mph`
        }))
      };

      return JSON.stringify(result, null, 2);
    } catch (error) {
      return `Failed to fetch weather: ${error.message}`;
    }
  },
};
