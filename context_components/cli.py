"""Structured offline command line. No implicit resource or tool discovery."""
import argparse
import os
from pathlib import Path
import sys
import tempfile

from .api import build_context,compose
from .common import COMPONENTS,ContextError,FileResolver,Services,dumps,fail,loads
from .adapters.core import ExportPolicy,adapt
from .render import render_context
from .presentation import CONTENT_FORMATS, EXPLANATION_DETAILS


def write_new(path, text):
    """Publish one new regular file atomically; never overwrite caller data."""
    target=Path(path).absolute()
    for parent in [target.parent,*target.parent.parents]:
        if parent.is_symlink():fail('forbidden_reference','Output parent is a symbolic link')
    if target.exists() or target.is_symlink():fail('forbidden_reference','Output already exists; select a new path')
    if not target.parent.is_dir():fail('invalid_request','Output parent directory does not exist')
    fd,tmp=tempfile.mkstemp(prefix='.context-output-',dir=target.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.link(tmp,target,follow_symlinks=False)
    except FileExistsError:fail('forbidden_reference','Output appeared during publication')
    finally:os.unlink(tmp)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component',choices=[*COMPONENTS,'compose','adapt'])
    parser.add_argument('--input',default='-');parser.add_argument('--output',default='-')
    parser.add_argument('--format',choices=['json','text','bundle'],default='json')
    parser.add_argument('--content-format',choices=CONTENT_FORMATS,
                        help='Agent text: JSON, English explanation + JSON (default), or English explanation with data; requires --format text or bundle')
    parser.add_argument('--explanation-detail', choices=EXPLANATION_DETAILS,
                        help='Full (default) or concise explanations; preserves all data and requires text or bundle output')
    parser.add_argument('--canonical-output')
    parser.add_argument('--resource-root');parser.add_argument('--resource-map')
    parser.add_argument('--benchmark');parser.add_argument('--public-paths');parser.add_argument('--catalog')
    parser.add_argument('--components',nargs='+',choices=COMPONENTS)
    parser.add_argument('--receiver-id',default='cli');parser.add_argument('--session-id',default='standalone')
    args=parser.parse_args(argv)
    try:
        if (args.content_format is not None or args.explanation_detail is not None) and args.format=='json':
            fail('invalid_request','--content-format/--explanation-detail requires --format text or bundle; --format json is always the canonical result')
        if args.input!='-':
            path=Path(args.input).absolute()
            request=loads(FileResolver(path.parent,{'input':path.name})({'uri':'input'}).data)
        else:request=loads(sys.stdin.buffer.read(8*1024*1024+1))
        resolver=None
        if bool(args.resource_root)!=bool(args.resource_map):fail('invalid_request','resource-root and resource-map must be supplied together')
        if args.resource_root:
            resolver=FileResolver(args.resource_root,loads(Path(args.resource_map).read_bytes()))
        if args.component=='adapt':
            if not args.benchmark or not args.public_paths:fail('invalid_request','adapt requires benchmark and a host public-paths file')
            policy=ExportPolicy(tuple(loads(Path(args.public_paths).read_bytes())),loads(Path(args.catalog).read_bytes()) if args.catalog else None)
            result=adapt(args.benchmark,request,policy=policy,components=args.components)
            if args.format!='json':fail('invalid_request','Adapt emits a canonical plan; execute compose before rendering')
        else:
            services=Services(resolver=resolver)
            result=compose(request,services=services) if args.component=='compose' else build_context(args.component,request,services=services)
        canonical=dumps(result)+'\n'
        if args.format=='json':text=canonical
        else:
            packet=render_context(result,dict(receiver_id=args.receiver_id,session_id=args.session_id,content_format=args.content_format or 'text_json',explanation_detail=args.explanation_detail or 'full',audience=dict(modalities=['text'] if args.format=='text' else ['text','image','video','audio'])))
            text=dumps(packet)+'\n' if args.format=='bundle' else '\n'.join(b.get('text','') for b in packet['blocks'])+'\n'
        if args.canonical_output:
            if args.canonical_output==args.output:fail('invalid_request','Canonical and rendered output paths must differ')
            write_new(args.canonical_output,canonical)
        if args.output=='-':sys.stdout.write(text)
        else:write_new(args.output,text)
        return 0
    except (ContextError,OSError) as exc:
        error=exc if isinstance(exc,ContextError) else ContextError('io_error',str(exc))
        sys.stdout.write(dumps(error.packet())+'\n')
        return 2


if __name__=='__main__':raise SystemExit(main())
