"""The config file schema: sources, plugins, libraries, and what gets refused."""

import json
import re
from pathlib import Path

import pytest
from kubed.mcp import TelemetrySettings, config_schema
from pydantic import ValidationError

from kubed.mcp_kb.config import (
    CREDENTIAL_REFUSAL,
    SECTIONS,
    BasicAuth,
    Config,
    ConfigError,
    EnvRef,
    PluginConfig,
    Selector,
    SourceConfig,
    Telemetry,
    load,
    schema,
)

SKETCH = """
sources:
- name: nextcloud
  url: webdav+http://nextcloud.cloud.svc.cluster.local:8080/remote.php/dav/files
  cache: live
  refresh: 15m
  auth:
    username: {env: NEXTCLOUD_USER}
    password: {env: NEXTCLOUD_PASSWORD}
- name: github
  url: git+https://github.com
  refresh: 1h

plugins:
- name: drive
  description: The ai Team folder in Nextcloud.
  category: homelab
  source: nextcloud://mcp-kb/ai
- name: team-notes
  category: engineering
  tags: [runbooks, oncall]
  source: github://my-team/my-repo//foo?ref=main
  skills: [./runbooks]
  prompts: [prompts/*.md]
  files: [shared/**]
- name: homelab-prompts
  category: observability
  source: file:///srv/prompts/grafana
  prompts: ["*.md"]

libraries:
- name: penpot
  source: github://penpot/penpot-ai-kit?ref=efbefc935ee43804502976aa5ec9659a8bb7e207
- name: grafana
  source: github://grafana/skills?ref=51d33e71e191b409bbd25fc7be2684c610d18166
  plugins: [homelab-prompts]
- name: kubed
  description: This homelab's own skills, prompts and agents.
  plugins: [drive]
- name: oncall
  description: Oncall runbooks and notes.
  pluginSelector:
    categories: [engineering, observability]
    tags: ["runbooks,oncall", lgtm]
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return path


def load_file(path: Path) -> Config:
    return load(["--config-file", str(path)], environ={}).config


def _sources(*extra: str) -> str:
    return "sources:\n- name: gh\n  url: git+https://github.com\n" + "".join(extra)


def _webdav(*extra: str) -> str:
    return (
        "sources:\n- name: nc\n  url: webdav+https://h/dav\n"
        "  auth: {username: me, password: {env: P}}\n" + "".join(extra)
    )


# -- the sketch ----------------------------------------------------------------


def test_the_sketch_config_parses(tmp_path):
    """The shape §C1.30 settled on: named sources, plugins, libraries."""
    config = load_file(write(tmp_path, SKETCH))

    assert [s.name for s in config.sources] == ["nextcloud", "github"]
    assert [p.name for p in config.plugins] == ["drive", "team-notes", "homelab-prompts"]
    assert [lib.name for lib in config.libraries] == [
        "penpot",
        "grafana",
        "kubed",
        "oncall",
    ]


def test_a_source_carries_its_backend_cache_and_refresh(tmp_path):
    config = load_file(write(tmp_path, SKETCH))

    nextcloud = config.source("nextcloud")
    assert nextcloud.backend == "webdav"
    assert nextcloud.cache == "live"
    assert nextcloud.refresh_seconds == 900
    assert config.source("github").backend == "git"
    assert config.source("github").cache == "snapshot"


def test_a_plugin_source_is_an_address_with_a_subdir_and_a_ref(tmp_path):
    config = load_file(write(tmp_path, SKETCH))
    address = config.plugins[1].address

    assert (address.scheme, address.path) == ("github", "my-team/my-repo")
    assert (address.subdir, address.ref) == ("foo", "main")


def test_a_plugin_carries_the_marketplace_entry_fields_and_its_globs(tmp_path):
    config = load_file(write(tmp_path, SKETCH))
    plugin = config.plugins[1]

    assert plugin.category == "engineering"
    assert plugin.tags == ["runbooks", "oncall"]
    assert plugin.skills == ["./runbooks"]
    assert plugin.prompts == ["prompts/*.md"]
    assert plugin.files == ["shared/**"]
    assert plugin.dialect == "auto"
    assert config.plugins[0].skills is None  # None means "use the conventions"


def test_a_library_selector_reads_categories_as_any_and_commas_as_all(tmp_path):
    config = load_file(write(tmp_path, SKETCH))
    selector = config.library("oncall").plugin_selector

    assert selector.category_set == frozenset({"engineering", "observability"})
    assert selector.tag_groups == frozenset(
        {frozenset({"runbooks", "oncall"}), frozenset({"lgtm"})}
    )


def test_a_library_normalises_its_categories():
    config = Config.model_validate(
        {
            "plugins": [{"name": "p", "source": "file:///p"}],
            "libraries": [
                {"name": "x", "plugins": ["p"], "categories": ["dev", " sp ", ""]}
            ],
        }
    )
    assert config.library("x").categories == ["dev", "sp"]


def test_an_undeclared_library_is_none_not_an_implicit_one(tmp_path):
    """A library is declared or it does not exist: `plugins` name real plugins."""
    config = load_file(write(tmp_path, SKETCH))

    assert config.library("grafana").name == "grafana"
    assert config.library("nope") is None


def test_an_undeclared_source_name_is_a_key_error(tmp_path):
    config = load_file(write(tmp_path, SKETCH))
    with pytest.raises(KeyError):
        config.source("nope")


# -- sources -------------------------------------------------------------------


def test_a_file_source_needs_no_auth_and_no_scheme_entry(tmp_path):
    config = load_file(
        write(tmp_path, "sources:\n- name: local\n  url: file:///srv\n")
    )
    assert config.source("local").backend == "file"


def test_a_source_may_not_be_named_for_a_builtin_scheme(tmp_path):
    """`file://` is built in, so a source called `file` could never be addressed."""
    with pytest.raises(ConfigError, match="file"):
        load_file(write(tmp_path, "sources:\n- name: file\n  url: file:///srv\n"))


def test_an_unknown_source_scheme_names_the_schemes_that_exist(tmp_path):
    with pytest.raises(ConfigError, match="webdav\\+https"):
        load_file(write(tmp_path, "sources:\n- name: a\n  url: ftp://a\n"))


def test_a_relative_file_url_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="absolute"):
        load_file(
            write(tmp_path, "sources:\n- name: a\n  url: file://relative/path\n")
        )


@pytest.mark.parametrize("name", ["Bad", "-a", "a-", "a" * 65, "a/b", ".."])
def test_a_bad_source_name_is_rejected_not_slugged(tmp_path, name):
    with pytest.raises(ConfigError):
        load_file(write(tmp_path, f"sources:\n- name: '{name}'\n  url: file:///a\n"))


@pytest.mark.parametrize("name", ['"valid\\n"', '"va\\nlid"'])
def test_a_name_carrying_a_newline_is_refused_here_too(tmp_path, name):
    """`NAME` is anchored at both ends, and pydantic-core matches it with the
    Rust engine, whose `$` is the end of the string and nothing else. Python's
    `re` also matches before a *final* newline, which is how the same pattern
    accepted `"valid\n"` in `marketplace.py`. This pins the engine: these
    names stay refused whatever `regex_engine` a later pydantic defaults to."""
    with pytest.raises(ConfigError):
        load_file(write(tmp_path, f"sources:\n- name: {name}\n  url: file:///a\n"))


def test_live_caching_is_refused_on_a_git_source(tmp_path):
    """Revalidation is WebDAV's; on git it would be silently nothing."""
    with pytest.raises(ConfigError, match="webdav"):
        load_file(write(tmp_path, _sources("  cache: live\n")))


def test_live_caching_parses_on_a_webdav_source(tmp_path):
    text = _webdav("  cache: live\n")
    config = load_file(write(tmp_path, text))
    assert config.source("nc").cache == "live"


def test_a_webdav_source_without_auth_is_refused(tmp_path):
    """WebDAV is an authenticated backend; an anonymous one is a typo, not a
    mode -- and one that would only show up as a 401 at cold start."""
    text = "sources:\n- name: nc\n  url: webdav+https://cloud.example/dav/notes\n"
    with pytest.raises(ConfigError, match="auth"):
        load_file(write(tmp_path, text))


def test_an_unknown_cache_mode_is_refused(tmp_path):
    text = _webdav("  cache: sometimes\n")
    with pytest.raises(ConfigError, match="cache"):
        load_file(write(tmp_path, text))


def test_an_unknown_key_is_refused_not_ignored(tmp_path):
    with pytest.raises(ConfigError, match="inculde"):
        load_file(
            write(tmp_path, "sources:\n- name: a\n  url: file:///a\n  inculde: {}\n")
        )


@pytest.mark.parametrize("refresh", ["0s", "5", "5d", "-5m", "5ms", ""])
def test_a_malformed_refresh_interval_is_a_config_error(tmp_path, refresh):
    with pytest.raises(ConfigError):
        load_file(write(tmp_path, _sources(f"  refresh: '{refresh}'\n")))


def test_a_refresh_interval_becomes_seconds(tmp_path):
    config = load_file(write(tmp_path, _sources("  refresh: 2h\n")))
    assert config.source("gh").refresh_seconds == 7200


def test_no_refresh_interval_means_no_refresh(tmp_path):
    config = load_file(write(tmp_path, _sources()))
    assert config.source("gh").refresh is None
    assert config.source("gh").refresh_seconds is None


def test_min_refresh_seconds_is_the_smallest_among_sources(tmp_path):
    text = (
        "sources:\n"
        "- name: a\n  url: file:///a\n  refresh: 5m\n"
        "- name: b\n  url: file:///b\n"
        "- name: c\n  url: file:///c\n  refresh: 30s\n"
    )
    assert load_file(write(tmp_path, text)).min_refresh_seconds == 30


def test_min_refresh_seconds_is_none_when_no_source_has_one(tmp_path):
    assert load_file(write(tmp_path, _sources())).min_refresh_seconds is None


def test_secrets_come_from_the_sources_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXTCLOUD_USER", "service-account")
    monkeypatch.setenv("NEXTCLOUD_PASSWORD", "hunter2")
    config = load_file(write(tmp_path, SKETCH))

    assert sorted(config.secrets()) == ["hunter2", "service-account"]


def test_secrets_skip_a_reference_whose_variable_is_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXTCLOUD_USER", raising=False)
    monkeypatch.delenv("NEXTCLOUD_PASSWORD", raising=False)
    assert load_file(write(tmp_path, SKETCH)).secrets() == []


def test_a_credential_embedded_in_a_url_is_refused(tmp_path):
    """`auth` is the one way a credential reaches a remote, and this is why.

    pygit2 saves the clone's remote URL verbatim under the cache, and a source
    URL is interpolated into the errors `/health` publishes -- so a token in the
    URL is a token on disk and in a served body. Refused at the door instead,
    and the refusal itself must not repeat it back.
    """
    text = "sources:\n- name: p\n  url: git+http://x-access-token:ghp-secret@h/x\n"

    with pytest.raises(ConfigError, match="credential") as raised:
        load_file(write(tmp_path, text))

    assert "ghp-secret" not in str(raised.value)
    assert "x-access-token" not in str(raised.value)


def test_a_url_with_no_credential_in_it_is_reported_as_it_is(tmp_path):
    """The redaction must not eat an ordinary refusal: one an operator cannot
    match to a line of their config is no help. kubed-mcp never echoes a value,
    so the line is matched by the item's path and the scheme kb names."""
    with pytest.raises(ConfigError, match="ftp") as raised:
        load_file(write(tmp_path, "sources:\n- name: p\n  url: ftp://a\n"))

    assert "sources[0].url" in str(raised.value)
    assert "unknown source scheme 'ftp'" in str(raised.value)


def test_a_password_containing_an_at_is_not_half_echoed(tmp_path):
    text = (
        "sources:\n- name: notes\n  url: webdav+https://me:hun@ter2@cloud.example/dav\n"
    )
    with pytest.raises(ConfigError, match="credential") as raised:
        load_file(write(tmp_path, text))
    assert "ter2" not in str(raised.value)
    assert "hun" not in str(raised.value)


# -- plugins -------------------------------------------------------------------


def test_a_plugin_scheme_with_no_source_names_the_declared_sources(tmp_path):
    text = _sources() + "plugins:\n- name: p\n  source: nextcloud://a/b\n"
    with pytest.raises(ConfigError, match="nextcloud") as raised:
        load_file(write(tmp_path, text))
    assert "gh" in str(raised.value)


def test_the_builtin_file_scheme_needs_no_source(tmp_path):
    text = "plugins:\n- name: p\n  source: file:///srv/prompts\n"
    config = load_file(write(tmp_path, text))
    assert config.plugins[0].address.path == "/srv/prompts"


def test_a_malformed_plugin_address_is_a_config_error(tmp_path):
    text = "plugins:\n- name: p\n  source: not-an-address\n"
    with pytest.raises(ConfigError, match="address"):
        load_file(write(tmp_path, text))


def test_a_ref_on_a_non_git_source_is_refused(tmp_path):
    """A ref is a git concept; on WebDAV it would be accepted and ignored."""
    text = _webdav() + "plugins:\n- name: p\n  source: nc://folder?ref=main\n"
    with pytest.raises(ConfigError, match="git"):
        load_file(write(tmp_path, text))


def test_a_ref_on_a_git_source_parses(tmp_path):
    """A branch, with no `refresh:` on the source: accepted, not a config error.

    A moving ref is supported on purpose -- a sha pins, a branch floats and a
    restart re-fetches (§C1.17, §C1.18) -- and whether the source is asked "has
    it moved?" on a timer is a separate choice the operator makes. A config
    that refused this would have no way to track a branch at all.
    """
    text = _sources() + "plugins:\n- name: p\n  source: gh://o/r?ref=main\n"
    config = load_file(write(tmp_path, text))
    assert config.plugins[0].address.ref == "main"


@pytest.mark.parametrize("patterns", ["['/etc/**']", "['../x']"])
def test_a_glob_escaping_the_plugin_root_is_refused(tmp_path, patterns):
    text = (
        _sources() + f"plugins:\n- name: p\n  source: gh://o/r\n  files: {patterns}\n"
    )
    with pytest.raises(ConfigError, match="relative"):
        load_file(write(tmp_path, text))


@pytest.mark.parametrize("item", ["skills/*", "skills/?x", "skills/[ab]"])
def test_a_glob_in_skills_is_refused(item):
    """``skills:`` lists folders; a glob there is a config from before, not a path."""
    with pytest.raises(ValueError, match=re.escape(repr(item))):
        PluginConfig(name="p", source="file:///x", skills=["./ok", item])


def test_a_glob_in_prompts_or_files_is_still_a_glob():
    plugin = PluginConfig(
        name="p", source="file:///x", prompts=["prompts/*.md"], files=["shared/**"]
    )
    assert (plugin.prompts, plugin.files) == (["prompts/*.md"], ["shared/**"])


def test_skills_empty_serves_none(tmp_path):
    """``skills: []`` validates, and serves no skill: not even ``skills/<name>/``."""
    from kubed.mcp_kb.catalogue.snapshot import build_plugin, with_manifest
    from kubed.mcp_kb.plugins import plugin_from_config

    skill = tmp_path / "skills" / "a"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: a\ndescription: d\n---\nbody\n")
    declared = PluginConfig(name="p", source=f"file://{tmp_path}", skills=[])
    config = Config.model_validate({"plugins": [declared.model_dump()]})

    completed, globs = with_manifest(plugin_from_config(config, declared), tmp_path)
    record = build_plugin(completed, tmp_path, globs=globs)

    assert declared.skills == []
    assert globs.skills == ()
    assert record.status == "ok"
    assert record.skills == ()


def test_an_unknown_dialect_is_refused(tmp_path):
    text = _sources() + "plugins:\n- name: p\n  source: gh://o/r\n  dialect: gemini\n"
    with pytest.raises(ConfigError, match="dialect"):
        load_file(write(tmp_path, text))


# -- libraries -----------------------------------------------------------------


def test_a_marketplace_library_with_a_selector_is_refused(tmp_path):
    text = (
        _sources() + "libraries:\n- name: lib\n  source: gh://o/r\n"
        "  pluginSelector:\n    categories: [design]\n"
    )
    with pytest.raises(ConfigError, match="takes its shape from the marketplace"):
        load_file(write(tmp_path, text))


def test_a_marketplace_library_may_still_add_a_named_plugin(tmp_path):
    text = (
        _sources() + "plugins:\n- name: mine\n  source: gh://o/r\n"
        "libraries:\n- name: lib\n  source: gh://o/r2\n  plugins: [mine]\n"
    )
    config = load_file(write(tmp_path, text))
    assert config.library("lib").plugins == ["mine"]


def test_a_library_that_selects_nothing_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="selects nothing"):
        load_file(write(tmp_path, "libraries:\n- name: empty\n  description: x\n"))


def test_a_library_naming_an_undeclared_plugin_is_refused(tmp_path):
    text = "libraries:\n- name: lib\n  plugins: [ghost]\n"
    with pytest.raises(ConfigError, match="ghost"):
        load_file(write(tmp_path, text))


def test_a_library_may_name_a_marketplace_plugin_which_is_checked_later(tmp_path):
    """`entry@library` is resolved once the marketplace is read, not at load."""
    text = (
        _sources() + "libraries:\n- name: up\n  source: gh://o/r\n"
        "- name: mine\n  plugins: [grafana-lgtm@up]\n"
    )
    config = load_file(write(tmp_path, text))
    assert config.library("mine").plugins == ["grafana-lgtm@up"]


def test_a_library_marketplace_scheme_with_no_source_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="nope"):
        load_file(write(tmp_path, "libraries:\n- name: lib\n  source: nope://o/r\n"))


# -- duplicates and the schema -------------------------------------------------


def test_duplicate_source_names_are_refused(tmp_path):
    text = "sources:\n- name: a\n  url: file:///a\n- name: a\n  url: file:///b\n"
    with pytest.raises(ConfigError, match="duplicate"):
        load_file(write(tmp_path, text))


def test_duplicate_plugin_names_are_refused(tmp_path):
    text = (
        "plugins:\n- name: a\n  source: file:///a\n- name: a\n  source: file:///b\n"
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_file(write(tmp_path, text))


def test_duplicate_library_names_are_refused(tmp_path):
    text = (
        "plugins:\n- name: p\n  source: file:///a\n"
        "libraries:\n- name: a\n  plugins: [p]\n- name: a\n  plugins: [p]\n"
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_file(write(tmp_path, text))


def test_a_comma_in_a_category_is_refused_with_the_reason(tmp_path):
    text = (
        "libraries:\n- name: lib\n  pluginSelector:\n"
        "    categories: ['design,engineering']\n"
    )
    with pytest.raises(ConfigError, match="a plugin has one category"):
        load_file(write(tmp_path, text))


def test_the_published_schema_names_the_selector_by_its_alias():
    """`config.schema.json` is what an editor validates against, and the file
    says `pluginSelector` -- the field name behind it must not be what ships."""
    published = json.dumps(schema())

    assert "pluginSelector" in published
    assert "plugin_selector" not in published


def test_a_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="does not exist"):
        load_file(tmp_path / "nope.yaml")


def test_config_constructs_from_model_instances_not_only_dicts():
    config = Config(
        sources=[SourceConfig(name="a", url="file:///a")],
        plugins=[PluginConfig(name="p", source="a://x")],
    )
    assert config.plugins[0].address.scheme == "a"


def test_a_selector_defaults_to_selecting_without_constraint():
    selector = Selector()
    assert selector.category_set == frozenset()
    assert selector.tag_groups == frozenset()


# -- the pieces kept from before ------------------------------------------------


def test_an_env_ref_resolves_to_a_secret(monkeypatch):
    monkeypatch.setenv("TOKEN", "hunter2")
    secret = EnvRef(env="TOKEN").resolve()
    assert secret.get_secret_value() == "hunter2"
    assert "hunter2" not in repr(secret)


def test_an_unset_env_ref_is_a_config_error(monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    with pytest.raises(ConfigError, match="NOPE"):
        EnvRef(env="NOPE").resolve()


def test_an_auth_password_must_be_an_env_ref_not_a_literal(tmp_path):
    text = _sources("  auth:\n    username: x-access-token\n    password: hunter2\n")
    with pytest.raises(ConfigError):
        load_file(write(tmp_path, text))


@pytest.mark.unit
def test_a_username_can_be_a_literal_or_an_env_reference(monkeypatch):
    """A service account's name arrives in the same secret as its password.

    Writing it out in the config as well is how the two drift apart the day the
    account is recreated, so `{env:}` has to be accepted on both halves of the
    pair -- while GitHub's literal `x-access-token` keeps working.
    """
    monkeypatch.setenv("ACCOUNT", "mcp-kb")
    monkeypatch.setenv("SECRET", "hunter2")

    literal = BasicAuth(username="x-access-token", password={"env": "SECRET"})
    assert literal.user() == "x-access-token"

    referenced = BasicAuth(username={"env": "ACCOUNT"}, password={"env": "SECRET"})
    assert referenced.user() == "mcp-kb"
    assert referenced.password.resolve().get_secret_value() == "hunter2"


@pytest.mark.unit
def test_a_username_env_reference_that_is_unset_is_an_error(monkeypatch):
    monkeypatch.delenv("ABSENT", raising=False)
    auth = BasicAuth(username={"env": "ABSENT"}, password={"env": "ABSENT"})
    with pytest.raises(ConfigError):
        auth.user()


def test_library_notes_and_list_skills(tmp_path):
    lib = (
        "sources:\n- name: gh\n  url: git+https://github.com\n"
        "plugins:\n- name: p\n  source: gh://o/r\n"
        "libraries:\n- name: a\n  plugins: [p]\n"
    )
    config = load_file(write(tmp_path, lib + "  listSkills: false\n  notes: x\n"))
    [a] = config.libraries
    assert a.list_skills is False and a.notes == "x"

    [plain] = load_file(write(tmp_path, lib)).libraries
    assert plain.list_skills is True and plain.notes == ""

    with pytest.raises(ConfigError, match="list_skills"):
        load_file(write(tmp_path, lib + "  list_skills: false\n"))


def test_a_library_lists_a_category_once_in_the_order_given():
    config = Config.model_validate(
        {
            "plugins": [{"name": "p", "source": "file:///p"}],
            "libraries": [
                {"name": "x", "plugins": ["p"], "categories": ["b", "a", "b", " a "]}
            ],
        }
    )
    assert config.library("x").categories == ["b", "a"]


def test_a_library_named_like_the_server_is_refused():
    with pytest.raises(ValidationError, match="the server's own name"):
        Config.model_validate(
            {"libraries": [{"name": "mcp-kb", "source": "file:///x"}]}
        )


def test_no_telemetry_section_is_every_signal_off(tmp_path):
    config = load_file(write(tmp_path, ""))
    assert config.telemetry == Telemetry()
    assert isinstance(config.telemetry, TelemetrySettings)
    assert config.telemetry.profiles is None and config.telemetry.otel is False


def test_a_telemetry_section_parses(tmp_path):
    config = load_file(
        write(
            tmp_path,
            "telemetry:\n  profiles: http://pyroscope.example.com:4040\n"
            "  otel: true\n  tags: {team: platform}\n",
        )
    )
    assert config.telemetry.profiles.get_secret_value() == (
        "http://pyroscope.example.com:4040"
    )
    assert config.telemetry.otel is True
    assert config.telemetry.tags == {"team": "platform"}
    assert config.telemetry.profile_cpu is True


def test_a_typod_telemetry_key_is_refused(tmp_path):
    text = "telemetry:\n  profile: http://pyroscope.example.com\n"
    with pytest.raises(ConfigError, match="profile"):
        load_file(write(tmp_path, text))


@pytest.mark.parametrize(
    "host",
    ["pyroscope.example.com:4040", "pyroscope:4040", "[::1:4040", "[pyroscope]:4040"],
)
def test_a_credential_in_the_profiles_address_is_refused(tmp_path, host):
    # A short host keeps the token's tail inside pydantic's truncated input repr,
    # and a host urlsplit cannot parse must be refused too, not reported as it is.
    text = f"telemetry:\n  profiles: http://me:s3cret@{host}\n"
    with pytest.raises(ConfigError) as raised:
        load_file(write(tmp_path, text))
    assert "must not embed a credential" in str(raised.value)
    assert "s3cret" not in str(raised.value)


def test_the_schema_carries_the_telemetry_section():
    published = schema()
    assert published["properties"]["telemetry"]["$ref"].endswith("/Telemetry")
    model = published["$defs"]["Telemetry"]
    assert {"profiles", "otel", "tags"} <= set(model["properties"])
    assert model["additionalProperties"] is False


# -- one composed config: the file, env vars and flags ---------------------------


def test_an_env_var_sets_each_kind_of_item(tmp_path):
    environ = {
        "KB_SOURCES": json.dumps([{"name": "local", "url": "file:///srv"}]),
        "CACHE_DIR": str(tmp_path / "c"),
        "PORT": "9001",
        "TELEMETRY_PROFILE_CPU": "false",
        "DELIVERY_VIA": "local",
    }
    config = load([], environ=environ).config
    assert [s.name for s in config.sources] == ["local"]
    assert config.cache_dir == tmp_path / "c"
    assert (config.serving.port, config.serving.transport) == (9001, "http")
    assert config.serving.host == "0.0.0.0"
    assert config.telemetry.profile_cpu is False
    assert config.delivery.via == "local"


def test_a_flag_beats_its_env_var_and_the_file(tmp_path):
    path = write(tmp_path, "serving:\n  port: 7000\n")
    loaded = load(
        ["--config-file", str(path), "--port", "9002"], environ={"PORT": "9001"}
    )
    assert loaded.config.serving.port == 9002
    assert str(loaded.sources["serving.port"]) == "arg --port"


def test_kb_sources_replaces_the_files_list_whole(tmp_path):
    path = write(
        tmp_path,
        "sources:\n- name: a\n  url: file:///a\n- name: b\n  url: file:///b\n",
    )
    env = {"KB_SOURCES": json.dumps([{"name": "c", "url": "file:///c"}])}
    loaded = load(["--config-file", str(path)], environ=env)
    assert [s.name for s in loaded.config.sources] == ["c"]


def test_a_login_in_kb_sources_is_refused_unechoed():
    env = {
        "KB_SOURCES": json.dumps(
            [{"name": "g", "url": "git+https://me:s3cret@example.com"}]
        )
    }
    with pytest.raises(ConfigError) as raised:
        load([], environ=env)
    assert "must not embed a credential" in str(raised.value)
    assert "s3cret" not in str(raised.value) and "me:" not in str(raised.value)


@pytest.mark.parametrize(
    "address",
    [
        "http://me:s3cret@pyroscope.example.com:4040",
        "http://me:s3cret@[pyroscope.example.com",
    ],
)
def test_a_login_in_telemetry_profiles_is_refused_unechoed(address):
    with pytest.raises(ConfigError) as raised:
        load([], environ={"TELEMETRY_PROFILES": address})
    assert CREDENTIAL_REFUSAL in str(raised.value)
    assert "s3cret" not in str(raised.value)


def test_config_file_names_the_file_and_config_is_not_read(tmp_path):
    path = write(tmp_path, "sources:\n- name: local\n  url: file:///srv\n")
    assert load([], environ={"CONFIG": str(path)}).config.sources == []
    named = load([], environ={"CONFIG_FILE": str(path)}).config
    assert [s.name for s in named.sources] == ["local"]
    with pytest.raises(ConfigError, match=r"arg --config\)"):
        load(["--config", str(path)], environ={})


def test_a_missing_named_file_is_refused_by_its_path():
    with pytest.raises(ConfigError, match="config file /nope does not exist"):
        load(["--config-file", "/nope"], environ={})


@pytest.mark.parametrize("transport", ["sse", "streamable-http"])
def test_kb_serves_stdio_or_http_alone(transport):
    with pytest.raises(ConfigError, match=re.escape("serving.transport")):
        load(["--transport", transport], environ={})


def test_log_level_reads_case_insensitively_and_a_flag_beats_it():
    assert load([], environ={"LOG_LEVEL": "debug"}).config.serving.log_level == "DEBUG"
    flagged = load(["--log-level", "error"], environ={"LOG_LEVEL": "debug"})
    assert flagged.config.serving.log_level == "ERROR"
    assert load([], environ={}).config.serving.log_level == "INFO"


def test_the_schema_is_the_composed_one():
    published = schema()
    assert published == config_schema(*SECTIONS)
    props = published["properties"]
    assert {
        "sources", "plugins", "libraries", "cache_dir",
        "serving", "telemetry", "delivery",
    } <= set(props)
    assert (props["sources"]["env"], props["sources"]["arg"]) == (
        "KB_SOURCES", "--sources"
    )
    assert (props["cache_dir"]["env"], props["cache_dir"]["arg"]) == (
        "CACHE_DIR", "--cache-dir"
    )
    serving = published["$defs"]["Serving"]["properties"]
    assert serving["transport"]["enum"] == ["stdio", "http"]
    assert (serving["transport"]["default"], serving["host"]["default"]) == (
        "http", "0.0.0.0"
    )
    profiles = published["$defs"]["Telemetry"]["properties"]["profiles"]
    assert profiles["sensitive"] is True and "default" not in profiles
