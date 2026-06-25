# Changelog

## [1.10.0](https://github.com/jvik/fomo/compare/v1.9.0...v1.10.0) (2026-06-25)


### Features

* add current role assignments screen ([#22](https://github.com/jvik/fomo/issues/22)) ([e0a6ad6](https://github.com/jvik/fomo/commit/e0a6ad6961a10e5cbd6aebf0271189d7fcc648b7))
* **cli:** add --entra support for non-interactive activation ([322f99e](https://github.com/jvik/fomo/commit/322f99e59fc463339e688158ce55499034be3016))
* **cli:** add management group support for non-interactive role activation ([9f79acd](https://github.com/jvik/fomo/commit/9f79acd506d930e3e9c84cb6d194859bb60fc748))
* **cli:** add non-interactive role activation via CLI flags ([80574f5](https://github.com/jvik/fomo/commit/80574f55bdd147ed3b24bde168a9ec322490b60f)), closes [#20](https://github.com/jvik/fomo/issues/20)
* **cli:** enforce mutual exclusivity of --entra and --mg flags and require reason for mg activation ([795149e](https://github.com/jvik/fomo/commit/795149e2242da4ac4b7cd09593955e964850bd19))
* implement column sorting functionality in assignments screen ([215ec08](https://github.com/jvik/fomo/commit/215ec08aba9d5996420b4d15b1b9e478d11f7837))
* update active assignments retrieval to include all scopes ([ef914a2](https://github.com/jvik/fomo/commit/ef914a277884a085ac24d063b75201f7da192c25))

## [1.9.0](https://github.com/jvik/fomo/compare/v1.8.4...v1.9.0) (2026-06-25)


### Features

* add current role assignments screen ([e124cc0](https://github.com/jvik/fomo/commit/e124cc0b9793a8cb5ae3589443ac5fb5a6c439fd))
* add current role assignments screen ([#22](https://github.com/jvik/fomo/issues/22)) ([24fb249](https://github.com/jvik/fomo/commit/24fb2496cc7151b92b1928e34469998cee0eaf49))
* **cli:** add --entra support for non-interactive activation ([58bee74](https://github.com/jvik/fomo/commit/58bee743c611af2edf162180413f723eab8c53f0))
* **cli:** add management group support for non-interactive role activation ([855b080](https://github.com/jvik/fomo/commit/855b0808a2b732f3e0962777be2e00e7b814df6e))
* **cli:** add non-interactive role activation via CLI flags ([6cf1438](https://github.com/jvik/fomo/commit/6cf14383d8a993c90267d9c90a864a9c74282e5c)), closes [#20](https://github.com/jvik/fomo/issues/20)
* **cli:** enforce mutual exclusivity of --entra and --mg flags and require reason for mg activation ([ab80cb4](https://github.com/jvik/fomo/commit/ab80cb448f54dd57853ea63351fb9ce6d35a7239))
* **cli:** non-interactive PIM role activation without the TUI ([48014c9](https://github.com/jvik/fomo/commit/48014c9591eac08103548879f0ca64b10f12ef93))
* implement column sorting functionality in assignments screen ([a4fc3b3](https://github.com/jvik/fomo/commit/a4fc3b3ef3499bb1a7af28b4542f01a1db2c3c5c))
* update active assignments retrieval to include all scopes ([6277fad](https://github.com/jvik/fomo/commit/6277fad8a5575466c48b395ac8b3083db607f7b9))

## [1.8.4](https://github.com/jvik/fomo/compare/v1.8.3...v1.8.4) (2026-06-25)


### Bug Fixes

* simplify role update message in EntraRolesScreen ([daf01c1](https://github.com/jvik/fomo/commit/daf01c19a6cc2490755202153322b676285785c2))

## [1.8.3](https://github.com/jvik/fomo/compare/v1.8.2...v1.8.3) (2026-06-25)


### Bug Fixes

* enhance back action handling in ActivationScreen and improve subscription warning display in ScopeScreen ([bca380e](https://github.com/jvik/fomo/commit/bca380eb28ff153c80d7e949cd305810a8aec945))

## [1.8.2](https://github.com/jvik/fomo/compare/v1.8.1...v1.8.2) (2026-06-25)


### Bug Fixes

* remove redundant navigation instructions from subscription selection ([ef06681](https://github.com/jvik/fomo/commit/ef066810d38193781c9a29d5203541f257736681))

## [1.8.1](https://github.com/jvik/fomo/compare/v1.8.0...v1.8.1) (2026-06-25)


### Bug Fixes

* add priority to escape key bindings for improved navigation ([e82771b](https://github.com/jvik/fomo/commit/e82771bcd72970b312dbea6531f2161177b21c0a))
* add priority to escape key bindings for improved navigation ([031b52b](https://github.com/jvik/fomo/commit/031b52bd83a93269ffda8bc1e869edfbac4ae012))

## [1.8.0](https://github.com/jvik/fomo/compare/v1.7.0...v1.8.0) (2026-06-25)


### Features

* enhance Entra role management with threading support for cancellation ([662afa0](https://github.com/jvik/fomo/commit/662afa06b3325a858ff1ced98a88305a1d2f8134))

## [1.7.0](https://github.com/jvik/fomo/compare/v1.6.0...v1.7.0) (2026-06-25)


### Features

* introduce Entra role management with device code flow and error handling ([a4254f3](https://github.com/jvik/fomo/commit/a4254f367d80469bee3cf366ff11d5ef6cce1dd6))


### Bug Fixes

* update expiry formatting to return 'Permanent' and adjust display style in Entra roles screen ([6414d5a](https://github.com/jvik/fomo/commit/6414d5ab90049195661fce73aec52548892591f6))

## [1.6.0](https://github.com/jvik/fomo/compare/v1.5.0...v1.6.0) (2026-06-25)


### Features

* add duplicate binding for 'q' key to navigate back in roles screen ([032e6a4](https://github.com/jvik/fomo/commit/032e6a46b0d5a02780fa16c17b05af8b6129c28c))
* add toggle selection with 'x' key in roles and scope screens ([9942423](https://github.com/jvik/fomo/commit/9942423caf8eb9716f8014e92d5ce9a5ecce469e))
* deduplicate roles in roles screen based on role GUID and scope ([2e6e14f](https://github.com/jvik/fomo/commit/2e6e14f6e2b16a695388339a0425224e907001dd))

## [1.5.0](https://github.com/jvik/fomo/compare/v1.4.1...v1.5.0) (2026-06-24)


### Features

* Add active role indication and filtering to roles screen ([b2085dd](https://github.com/jvik/fomo/commit/b2085dd4105d1df91a8f9f7ab706d74ad9d7ab6a))


### Bug Fixes

* Update key bindings for role and scope screens ([5af4c5a](https://github.com/jvik/fomo/commit/5af4c5ab72087e74f42796abbfffbdb6b4812c9f))

## [1.4.1](https://github.com/jvik/fomo/compare/v1.4.0...v1.4.1) (2026-06-24)


### Bug Fixes

* Update activation completion handling with button state management and focus ([53ca56c](https://github.com/jvik/fomo/commit/53ca56c1671ca5e2b173382dbf48f3ca7d72f15a))

## [1.4.0](https://github.com/jvik/fomo/compare/v1.3.0...v1.4.0) (2026-06-24)


### Features

* Enhance role activation screen with improved status column width and error message formatting ([64e342b](https://github.com/jvik/fomo/commit/64e342b9ab17f6e5bdf725fbf3df335cc99a0fe9))
* Enhance role management with global role handling and UI updates ([aac533f](https://github.com/jvik/fomo/commit/aac533f18ac483e790e6ee6dee320e600a1dae7a))

## [1.3.0](https://github.com/jvik/fomo/compare/v1.2.0...v1.3.0) (2026-06-24)


### Features

* Add upgrade instructions to README ([56407b8](https://github.com/jvik/fomo/commit/56407b8522cdfdaefba42b33cdf6a71ebebc4b7d))


### Bug Fixes

* Replace duration input with a select dropdown for better usability ([78cc135](https://github.com/jvik/fomo/commit/78cc135fbcc7b493920d7decc3537bfe1596e729))
* Update key bindings for clarity in roles and scope screens ([56407b8](https://github.com/jvik/fomo/commit/56407b8522cdfdaefba42b33cdf6a71ebebc4b7d))

## [1.2.0](https://github.com/jvik/fomo/compare/v1.1.0...v1.2.0) (2026-06-24)


### Features

* Add logging functionality and error handling to activation process ([413c1cf](https://github.com/jvik/fomo/commit/413c1cf018709e4b16e482545b33a4fc0495c10d))
* Add README file with installation and usage instructions ([706b0bd](https://github.com/jvik/fomo/commit/706b0bd3b612ee01eed99869b9b7ae7ad6552e6a))


### Bug Fixes

* Update installation instructions in README for clarity ([8b0f851](https://github.com/jvik/fomo/commit/8b0f85135620b33d0cbb8ecb1622a6037f2c9a20))

## [1.1.0](https://github.com/jvik/fomo/compare/v1.0.0...v1.1.0) (2026-06-24)


### Features

* Enhance release workflow with build and publish steps ([ec74f74](https://github.com/jvik/fomo/commit/ec74f74d50c0e600da0abadf5e62d3a667e72daf))

## 1.0.0 (2026-06-24)


### Bug Fixes

* Added release please ([f1e3999](https://github.com/jvik/fomo/commit/f1e399977aff7ad511f13f1f0e64a5328c134a90))
