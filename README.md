# Rain Bird Cloud for Home Assistant

Controls a Rain Bird controller through Rain Bird's cloud, signing in with the same account as the Rain Bird 2.0 app.

Use this when the built-in Rain Bird integration can no longer sign in to your controller locally. For example, an ARC6 on firmware 4.103 refuses the 6-digit PIN for local access.

Shared as is. Issues are not monitored.

## What you get

- A switch per zone. Turning it on runs the zone for the default watering time (6 minutes, changeable under Configure). Turning it off stops watering.
- **Stop watering** button.
- A **Run …** button for each program on the controller.
- **Rain delay** (0 to 14 days).
- **Rain sensor**, when the controller has one wired.
- **Watering now** and **Time remaining** sensors.

Live zone and rain sensor state come from Rain Bird's real-time feed, the same one the app uses. Rain delay is polled every minute.

## Install

1. In HACS, open the three-dot menu and choose **Custom repositories**. Add this repository as type **Integration**.
2. Download **Rain Bird Cloud**, then restart Home Assistant.
3. Go to **Settings › Devices & services › Add integration › Rain Bird Cloud** and sign in with your Rain Bird account.

## Limits

- It needs the internet and Rain Bird's servers. If either is down, Home Assistant can't control the controller.
- This uses Rain Bird's unofficial cloud interface, through [pyrainbird](https://github.com/allenporter/pyrainbird). Rain Bird can change or close it at any time.
- Turning off any zone stops all watering, because that's what the controller supports.
