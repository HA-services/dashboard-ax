# FAQ

**Does it work on Odoo Online?** Custom modules can only be installed on Odoo.sh and on premise. Odoo Online does not allow third party modules.

**Does it need Enterprise?** No. It depends on base, web and mail only.

**Does it use sudo?** No. Every item runs with the viewer's rights.

**Can users see data they should not?** Not through Odoo model items. SQL and external items bypass record rules by nature, so they are Manager only.

**Can I use my own AI provider?** Yes, any OpenAI compatible endpoint or Anthropic.

**Is real-time refresh supported?** Items refresh on an interval you choose. Push updates are not implemented.

**Is the map detailed?** Country level only.

**Is MySQL supported?** Yes, with `pymysql` installed. PostgreSQL is supported out of the box.

**Does it support right to left languages?** It relies on Odoo's own handling. Layout direction inside the grid has not been tested exhaustively.

**Can I migrate to another Odoo version?** Dashboards can be exported as JSON and imported into the same module on another version.

**How are updates delivered?** Through the Apps Store listing for your version.
