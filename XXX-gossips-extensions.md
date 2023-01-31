# Staking Credentials -- Gossips Extensions

This document specifies the BOLT 7 Gossips Extensions inside the the Staking Credentials framework.

The message data format, validation algorithms and implementations considerations are laid out.

This draft is version 0.1 of the Gossips Extensions.

## The `credential_policy` message

This gossip message contains informations regarding an Issuer's liquidity collateral acceptance and
credential policy. It ties a list of asset proofs and credentials to the associated Issuer node key.

## The `contract_policy` message

This gossip message contains informations regarding a Contract's liquidity risk-management policy.
It ties a list of credential issuers and the covered contracts to the associated Contract Provider
node key.
