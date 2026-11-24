# Android Gradle smoke check

Run from the repository root on the `conduktor/UTB-1` checkout.

- Task: `./gradlew :smarttubetv:assembleStutubotDebug`
- Result: succeeded

The first attempt failed during configuration because the sibling
`SharedModules` checkout was ahead of the pinned commit and its
`constants.gradle` no longer defined `phoenixVersion`. Once that checkout was
at the pinned commit, the task completed.

Last 20 lines of Gradle output:

```
> Task :smarttubetv:processStutubotDebugResources
> Task :smarttubetv:dexBuilderStutubotDebug
> Task :smarttubetv:mergeStutubotDebugNativeLibs
> Task :smarttubetv:stripStutubotDebugDebugSymbols
> Task :smarttubetv:mergeProjectDexStutubotDebug
> Task :smarttubetv:packageStutubotDebug
> Task :smarttubetv:createStutubotDebugApkListingFileRedirect
> Task :smarttubetv:assembleStutubotDebug

[Incubating] Problems report is available at: file:///var/lib/conduktor/worktrees/f612887a5a867fe3b36be26cf877409a/UTB/UTB-1/build/reports/problems/problems-report.html

Deprecated Gradle features were used in this build, making it incompatible with Gradle 10.

You can use '--warning-mode all' to show the individual deprecation warnings and determine if they come from your own scripts or plugins.

For more on this, please refer to https://docs.gradle.org/9.6.1/userguide/command_line_interface.html#sec:command_line_warnings in the Gradle documentation.

BUILD SUCCESSFUL in 1m 19s
514 actionable tasks: 514 executed
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.6.1/userguide/configuration_cache_enabling.html
```
