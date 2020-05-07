If you find any bugs, vulnerabilites or undefined behavior while reviewing a Lightning
implementation we invite you to conform to the following guidelines:

* First, with a best-effort, identify and try to reproduce the behavior in a faithful way,
with commit and configuration
* If the faultive behavior is implementation-specific, please contact maintainers of the project
following their security policy (Eclair, LND, C-lightning, Rust-Lightning, Electrum, ptarmigan) XXX link them
* We invite to keep in mind that faultive behavior may be due to a dependency. In this case you
may have other non-LN bitcoin projects using it, their maintainers should be informed
* If the faultive behavior is due to the spec or first-layer, please contact at least maintainers of each project and express your concerns
* Leading to patching one implementation may raise awareness on critical part of other implementation, themselves at risk, therefore to prevent such outcome,
ensure the party disclosed to coordinate with the rest of ecosystem if necessary
* You should try to scope the difficulty of exploitation and class of LN nodes affected (routing vs non-routing).
* A vulnerability may lead to the non-exhaustive non-disjunction cases: fund loss, fund freeze, third-party channel closure, netsplit, privacy leak, channel DoS, feerate inflation, ...
* Be patient, people invovled are likely spread on a timezone different than yours or travelling without full access to their security PGP keys. However if you don't get any response after a week, please try to contact them via a different communication channel asking them to check their security mailbox.
* Keep in mind you're dealing with people money, and mistakes can lead to funds loss. Act with caution.

* XXX: (timeline and deployment, type of disclosure ?

Above all, we deeply thanks you to take part to the review and security process of the Lightnig Network and dedicating time to build a more trustworthy off-chain layer.
