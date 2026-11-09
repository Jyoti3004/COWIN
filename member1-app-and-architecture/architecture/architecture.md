# CoWIN Multi-Zone / Multi-Region Architecture

## Reference design (Mermaid – renders on GitHub)
```mermaid
flowchart TB
    U[Citizens / Hospitals / Third-party apps] --> DNS[DNS with health-check failover]
    DNS --> CDN[CDN + WAF<br/>cache, rate limit, CAPTCHA]

    subgraph R1[Region 1 - Mumbai ap-south-1]
        LB1[Application Load Balancer]
        subgraph AZ1A[AZ ap-south-1a]
            A1[App: Registration / Scheduling / Lookup]
            DB1[(Primary DB)]
        end
        subgraph AZ1B[AZ ap-south-1b]
            A2[App: Registration / Scheduling / Lookup]
            DB2[(Standby DB - sync replica)]
        end
        Q1[[Booking queue]]
        C1[(Cache)]
        LB1 --> A1
        LB1 --> A2
        A1 --> C1
        A2 --> C1
        A1 --> Q1
        A2 --> Q1
        Q1 --> DB1
        DB1 -. synchronous .-> DB2
    end

    subgraph R2[Region 2 - Hyderabad ap-south-2 - Disaster Recovery]
        LB2[Load Balancer]
        A3[App tier - warm standby]
        DB3[(Read replica / DR DB)]
        LB2 --> A3 --> DB3
    end

    CDN --> LB1
    CDN -. failover .-> LB2
    DB1 -. async cross-region .-> DB3
```

## What we actually built (PoC scope)
```mermaid
flowchart LR
    T[failover_test.py<br/>10 req/s] --> LB[Load Balancer<br/>ALB / nginx / lb.py]
    LB --> ZA[Zone A: ap-south-1a<br/>Vaccine Center Lookup]
    LB --> ZB[Zone B: ap-south-1b<br/>Vaccine Center Lookup]
    X((Chaos: kill Zone A)) -.-> ZA
```

## Request flow
1. Citizen opens app → DNS returns the healthy region.
2. CDN/WAF serves cached slot data and throttles abusive clients.
3. Load balancer sends the request to a healthy app node in either AZ.
4. Reads hit the cache; booking writes go via a queue to the primary database.
5. Database replicates synchronously to the standby AZ and asynchronously to the DR region.
6. If a node/AZ fails, health checks remove it; if a region fails, DNS fails over to Region 2.

## Failure scenarios
| Failure | Detection | Result |
|---|---|---|
| App node crash | LB health check | Traffic goes to the other AZ (demonstrated in our PoC) |
| Entire AZ outage | LB health check | Other AZ serves; DB standby promoted |
| Whole region outage | DNS health check | Failover to Hyderabad (warm standby) |
| Traffic spike | CPU/request metrics | Auto Scaling adds nodes; CDN/cache absorbs reads |

*Export the first diagram to PNG/SVG (https://mermaid.live) for the report and slides.*
