# Configuration Directory

This directory will contain version-controlled, non-secret configuration
for forecast models, validation rules, storage paths, and orchestration.

Credentials, service-account keys, local environment files, and provider
tokens must not be stored here.

Planned configuration files include:

- model definitions
- expected forecast-hour schedules
- expected ensemble-member definitions
- required GRIB variables and levels
- Google Cloud Storage prefix configuration
- retry and timeout policies
- mandatory versus optional model stages
