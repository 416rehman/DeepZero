# Changelog

## [0.4.0](https://github.com/416rehman/DeepZero/compare/deepzero-v0.3.0...deepzero-v0.4.0) (2026-07-27)


### Features

* **decompile:** record whether a device exists without the hardware ([6030ae1](https://github.com/416rehman/DeepZero/commit/6030ae113c3a4f5a3556e4e062c77fe7ca05a73f)), closes [#20](https://github.com/416rehman/DeepZero/issues/20)
* **engine:** tell running out of time apart from going wrong ([696a46b](https://github.com/416rehman/DeepZero/commit/696a46b0e1552a2cc01807a659df84cf09fac132)), closes [#19](https://github.com/416rehman/DeepZero/issues/19)
* **pipeline:** catch a prompt asking for values no stage produces ([1c937fa](https://github.com/416rehman/DeepZero/commit/1c937fa36e7a70b664490dccc46e7588e7a38ebd)), closes [#23](https://github.com/416rehman/DeepZero/issues/23)
* **report:** let the reader record what they have actually checked ([523ed1a](https://github.com/416rehman/DeepZero/commit/523ed1a7385a0b5e5c6ded7002ff8195b57899c9)), closes [#24](https://github.com/416rehman/DeepZero/issues/24)
* **report:** rank results in one list and rebuild the palette ([9aafd6a](https://github.com/416rehman/DeepZero/commit/9aafd6a79c2bdd313be0b8f70d379220cecf4b30))
* **report:** record a result that was checked and did not hold up ([3fd55ac](https://github.com/416rehman/DeepZero/commit/3fd55acc43e617b7d9545a13ccb2e3aefd60ebcb)), closes [#25](https://github.com/416rehman/DeepZero/issues/25)


### Bug Fixes

* **report:** tell the two kinds of filter apart ([6aa9320](https://github.com/416rehman/DeepZero/commit/6aa9320eb2aa057018d1c8c574208362aa039d00))
* **scan:** stop one bad batch from discarding a whole corpus of results ([6a6badf](https://github.com/416rehman/DeepZero/commit/6a6badf81b905ba151c283aed2b9c7af3ba542f2)), closes [#21](https://github.com/416rehman/DeepZero/issues/21)
* **test:** check the bundled prompt without needing a full environment ([5c0fbda](https://github.com/416rehman/DeepZero/commit/5c0fbda75fffac185d867d48d8fb73e9a65d23a7))


### Refactors

* **report:** name the two assessment outcomes for what they are ([93619be](https://github.com/416rehman/DeepZero/commit/93619be980f8f3ff575b06c0a604e220d2ee1118))


### Documentation

* **decompile:** record what decompilation writes and guard its shape ([ccca456](https://github.com/416rehman/DeepZero/commit/ccca45633155df95e492bd4cd0b136bb2b9ffcbe)), closes [#22](https://github.com/416rehman/DeepZero/issues/22)

## [0.3.0](https://github.com/416rehman/DeepZero/compare/deepzero-v0.2.0...deepzero-v0.3.0) (2026-07-26)


### Features

* add a preflight check that catches an unauthenticated LLM before a run ([d6023d6](https://github.com/416rehman/DeepZero/commit/d6023d612da5c4925fc09de868ffe63470c1aaa6))
* assess drivers with Opus in the bundled loldrivers pipeline ([190aeb5](https://github.com/416rehman/DeepZero/commit/190aeb515866bfc9cd90b9d662ae517585d450c7))
* assess every driver that survives scanning, worst first ([0b1f899](https://github.com/416rehman/DeepZero/commit/0b1f89966c939b0364d3072af501aa9dbbb494af))
* browse a run's results in the browser, plus resume and auth fixes ([cf6a7d0](https://github.com/416rehman/DeepZero/commit/cf6a7d09089e4e354e0dc97bd2d0d738421a5311))
* Claude Code LLM backend (no API key) + fixes to run the loldrivers pipeline end-to-end on Windows ([1c3e0e2](https://github.com/416rehman/DeepZero/commit/1c3e0e287e7cb6122561587d918ff097dc07151e))
* **cli:** calculate running stage stats dynamically from live manifest for real-time status accuracy ([c4e467c](https://github.com/416rehman/DeepZero/commit/c4e467cad447a5ebb3e0889c7dbf0dd3edf358bc))
* **cli:** scope each run's work directory per corpus ([8f0e973](https://github.com/416rehman/DeepZero/commit/8f0e973ab25c680997a2d0e5a4fd53f0b89d397b))
* max concurrency pooling and rich progress bars ([65397dd](https://github.com/416rehman/DeepZero/commit/65397ddff918a612780bcaee7fee579e2d2f9d91))
* report a vulnerability with what is needed to reproduce it ([1ff9f7c](https://github.com/416rehman/DeepZero/commit/1ff9f7c79ef96876c5415d2601276a67d81cc545))
* review a run's results in the browser with `deepzero report` ([f2f8fe4](https://github.com/416rehman/DeepZero/commit/f2f8fe4ed9ad2aba6d61fc8f5476c6b0ca6429b8))
* run pipelines with your Claude Code subscription, no API key required ([d83d171](https://github.com/416rehman/DeepZero/commit/d83d1711e0cee6f9c5ad88614a2795b30a122790))
* run the bundled loldrivers pipeline on Claude Code out of the box ([9b41502](https://github.com/416rehman/DeepZero/commit/9b41502198bfb960bf1a9b5b1622c9248b77d013))
* **ui:** complete overhaul of CLI dashboard and pipeline visualizations ([4485608](https://github.com/416rehman/DeepZero/commit/4485608e7660898ea1a13c76073a800d94ae24fb))


### Bug Fixes

* bound decompilation concurrency ([#12](https://github.com/416rehman/DeepZero/issues/12)) + add auth preflight ([#14](https://github.com/416rehman/DeepZero/issues/14)) ([c71dba1](https://github.com/416rehman/DeepZero/commit/c71dba1454e30059f2b91e7c5f858646ba665393))
* cap decompilation concurrency so large runs don't exhaust memory ([a9ed18f](https://github.com/416rehman/DeepZero/commit/a9ed18f60168a00f9d1141312bd22628a9e01173))
* **cli:** align status table to unconditionally display all pipeline stages in sequence ([d60e30d](https://github.com/416rehman/DeepZero/commit/d60e30d1c185c8c7a21b499ee5ea8ac69a516e53))
* **cli:** bypass manifest cache and calculate stats directly from live sample files ([1a5ce38](https://github.com/416rehman/DeepZero/commit/1a5ce38c0468a72cc8ec1e9ea4163f3e8391dca5))
* **cli:** gracefully handle validation and authorization exceptions without dumping tracebacks ([66269a8](https://github.com/416rehman/DeepZero/commit/66269a8b0ff2dfabf4ea81993fc51af667dbffe4))
* **cli:** uniformly load environment variables in dry-run commands ([05f621e](https://github.com/416rehman/DeepZero/commit/05f621ed001c84141a1a1dc8ed432b7cdebe20ff))
* decompile drivers that expose IOCTL handlers ([dd0e861](https://github.com/416rehman/DeepZero/commit/dd0e861e06d3eaee8d9191420c5e592fa5f58bc1))
* explain why a vulnerability scan failed instead of failing silently ([cab855c](https://github.com/416rehman/DeepZero/commit/cab855c278dadb8a786ae7e6f7637a98a333ae68))
* explicit internal dev bindings mapping pytest-asyncio directly against Github Actions environment containers ([3de5cba](https://github.com/416rehman/DeepZero/commit/3de5cba7473549ef13028b6e2e2f23094ece7a7f))
* **ghidra:** resolve UnicodeEncodeError in Jython environment ([7eaa260](https://github.com/416rehman/DeepZero/commit/7eaa260114cb00006b1abdde97b9cc2fcfac2e33))
* **ghidra:** sync internal timeout to prioritize global StageSpec timeouts ([b8cd205](https://github.com/416rehman/DeepZero/commit/b8cd2055cc04ffc87977885fbb1c4b395eb88b44))
* give a clear error when the vulnerability scan can't find its rules ([dc2fee1](https://github.com/416rehman/DeepZero/commit/dc2fee1d5058c8dd46cbe7ceebea3698ab9af5b5))
* give the model the driver code it is asked to assess ([caa3b0d](https://github.com/416rehman/DeepZero/commit/caa3b0d05b3f34bcd35f7d326e236c7d6a93d90d))
* globally silence tool info logs during progress loop ([fae8541](https://github.com/416rehman/DeepZero/commit/fae8541f68fd6851fe2a619a4fcd39569448be25))
* keep already-analysed samples in the pipeline when a run resumes ([64f0003](https://github.com/416rehman/DeepZero/commit/64f0003fe2fd19175ca268c90967e621ca2ef6d0))
* keep runs from crashing when printing results on Windows ([981c684](https://github.com/416rehman/DeepZero/commit/981c6845ab181a0a857b322c3a43472d82bbf3c6))
* **runner:** flush active manifest metrics and state.json on forced sigint hard-kills ([036bb1c](https://github.com/416rehman/DeepZero/commit/036bb1c303f21d7248052cbb4624b0443cfe620c))
* say whether a run is still going, not just what it last claimed ([9dc0fb3](https://github.com/416rehman/DeepZero/commit/9dc0fb388cd58dfd3499fb3edf64bd416b7066aa))
* say whether a sample was examined or excluded ([a2b471e](https://github.com/416rehman/DeepZero/commit/a2b471ec4de1b3e21034fc0b5f32e718ffd2d535))
* scan large corpora without losing every result ([210f49f](https://github.com/416rehman/DeepZero/commit/210f49f43b14923cecb4a75360f511e59951f924))
* show a clear error when a required pipeline setting is missing ([9330427](https://github.com/416rehman/DeepZero/commit/9330427649e17c9cc20c3587ca67426773e2ec5b))
* show results as they land, and explain every outcome label ([e687c75](https://github.com/416rehman/DeepZero/commit/e687c75e176ce76720a26d98950e9f4c5192232f))
* **stage:** import threading for type hints ([7664d5c](https://github.com/416rehman/DeepZero/commit/7664d5c5ec1228bb8981e6678becf16e038d1a41))
* stop scanning the same routine once per IOCTL code ([0a9146b](https://github.com/416rehman/DeepZero/commit/0a9146b1f1c148ed148732559ae354bbd1065294))
* stop the driver vulnerability scan from silently finding nothing ([ec7ea00](https://github.com/416rehman/DeepZero/commit/ec7ea0068b0136ca7cc5767cc3cb4816a4d2c272))
* tell the user how to fix Claude Code auth when it is not signed in ([07c85f3](https://github.com/416rehman/DeepZero/commit/07c85f38b0d3589c6bef8d0d1b836689a4e4e5c8))


### Refactors

* complete processor architecture and pipeline engine overhaul ([7d67f93](https://github.com/416rehman/DeepZero/commit/7d67f93dcb4fea201f6d4f39ffce39a55bc5ecde))
* drop #nosec tag and switch ghidra decompile processor to native asyncio execution ([8413638](https://github.com/416rehman/DeepZero/commit/841363866bf2fb5e759ae011e70bc0462229bb33))
* extract subprocess utils to engine/process.py, rename _run_inner, add --model to resume ([9776aae](https://github.com/416rehman/DeepZero/commit/9776aae88c03a23a17beacb42de7b8d3d2b848bf))
* resolve pipeline coupling and technical debt ([8764640](https://github.com/416rehman/DeepZero/commit/8764640c9ff1e21260571bf0211800d792dc0232))
* simplify logging color schema and enforce proper signal handling encapsulation ([06e68c1](https://github.com/416rehman/DeepZero/commit/06e68c13aca5b6fe03cafed72951d1400f5883a4))


### Documentation

* add .env.example template for quick setup ([2948862](https://github.com/416rehman/DeepZero/commit/294886299a0414d63fd5765970c44dae2dc2de58))
* add code of conduct, contributing guide, issue and PR templates ([#8](https://github.com/416rehman/DeepZero/issues/8)) ([030e962](https://github.com/416rehman/DeepZero/commit/030e962b9359f22f91c8d6a1b2105cab82821460))
* Completely overwrite README to precisely standardize project architecture and workflow execution schema ([49a749f](https://github.com/416rehman/DeepZero/commit/49a749f22950fe3e9ed9775acc79792b91818545))
* fix baseurl for github pages routing ([#10](https://github.com/416rehman/DeepZero/issues/10)) ([eb0e775](https://github.com/416rehman/DeepZero/commit/eb0e775909b1d6a45ac1628ff9295172d64e1ffb))
* overhaul README with updated features and architecture ([6afd696](https://github.com/416rehman/DeepZero/commit/6afd6969dc93fbc2147198e1abc5d5f596fe11f2))
* prominently mark REST API as WIP / experimental in CLI usage section ([98c3d6d](https://github.com/416rehman/DeepZero/commit/98c3d6d25cab2bfe8f741e27caa8defbbe5bb20e))
* prominently mark REST API as WIP / experimental in CLI usage section ([82a4d2a](https://github.com/416rehman/DeepZero/commit/82a4d2a88627a7344079c1de1d83461b5c6da93b))
* streamline quickstart and eliminate fragmented installation section ([4640b6c](https://github.com/416rehman/DeepZero/commit/4640b6c055597b9c1e15c6958e535be83303107e))
* strip explicitly opinionated terminology and genericize README scope correctly ([4382889](https://github.com/416rehman/DeepZero/commit/438288963cdad1dd8b95666b30483814825012f0))
* update readme with new documentation links ([#11](https://github.com/416rehman/DeepZero/issues/11)) ([c6ef8a9](https://github.com/416rehman/DeepZero/commit/c6ef8a9a7c073031cc2186f0721ef9862df41615))
* use mark_interrupted ([6ff7ad1](https://github.com/416rehman/DeepZero/commit/6ff7ad10b3b4fbf15f243bc9e74c298cb8a5a411))
