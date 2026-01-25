# Migration Guide: Standalone → Serverless

## Overview

In v2.2.27, we renamed the "Standalone" classes to "Serverless" for better clarity. This is a simple import path change with no functionality changes.

## What Changed

### Class Names
- `StandaloneProducer` → `ServerlessProducer`
- `StandaloneClient` → `ServerlessClient`

### Module Path
- `tchu_tchu.standalone_producer` → `tchu_tchu.serverless_producer`

## Migration

### Before (v2.2.27)
```python
from tchu_tchu.standalone_producer import StandaloneClient

client = StandaloneClient(broker_url=BROKER_URL)
client.publish('event.name', data)
```

### After (v2.2.27+)
```python
from tchu_tchu.serverless_producer import ServerlessClient

client = ServerlessClient(broker_url=BROKER_URL)
client.publish('event.name', data)
```

## Why the Change?

"Serverless" better describes the intended use case (Cloud Functions, Lambda, etc.) compared to "Standalone" which could be ambiguous.

## Functionality

No functionality changes - this is purely a naming improvement for clarity.

